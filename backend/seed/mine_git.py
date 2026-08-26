"""Mine a real git repository's commit history into structured records.

Shells out to the `git` CLI (no extra dependency) and parses `git log
--numstat` output into commits, each carrying the files it touched. This is
the "real seed data" source for the app -- no synthetic generation involved.
"""
import os
import posixpath
import shutil
import stat
import subprocess
from dataclasses import dataclass, field

RECORD_SEP = "\x1e"
FIELD_SEP = "\x1f"


class GitOperationError(RuntimeError):
    """Raised when a `git` subprocess fails or exceeds its timeout.

    Untrusted, user-supplied repo URLs drive these calls (the ingest API
    lets anyone point at "any public repo"), so every one of them needs a
    bound: an unreachable host or a repo with a huge history must fail
    loudly within a fixed budget rather than hang the caller indefinitely.
    """


def _extension_of(path: str) -> str:
    _, ext = posixpath.splitext(path)
    return ext.lstrip(".").lower()


def _module_of(path: str, depth: int) -> str:
    parts = path.split("/")
    if len(parts) <= 1:
        return "root"
    return "/".join(parts[:depth]) or "root"


@dataclass
class FileChange:
    path: str
    additions: int
    deletions: int
    change_type: str  # M (modify/add/delete -- numstat doesn't disambiguate) or R (rename)
    old_path: str | None = None  # set only for renames; path this file was renamed from

    @property
    def extension(self) -> str:
        return _extension_of(self.path)

    def module(self, depth: int) -> str:
        return _module_of(self.path, depth)


@dataclass
class Commit:
    hash: str
    author_name: str
    author_email: str
    timestamp: str
    message: str
    files: list[FileChange] = field(default_factory=list)

    @property
    def additions(self) -> int:
        return sum(f.additions for f in self.files)

    @property
    def deletions(self) -> int:
        return sum(f.deletions for f in self.files)


def _rmtree(path: str) -> None:
    """Remove a directory tree, including a previous git clone's contents.

    Plain shutil.rmtree(ignore_errors=True) can silently leave files behind
    on Windows: git marks packed objects read-only, and a read-only file
    can't be unlinked without clearing that bit first. Left behind, the next
    `git clone` into the same directory fails with "already exists and is
    not an empty directory" -- so this clears the bit and retries instead of
    swallowing the failure.
    """
    def _clear_readonly_and_retry(func, path, exc_info):  # noqa: ANN001 - shutil.rmtree onerror signature
        os.chmod(path, stat.S_IWRITE)
        func(path)

    shutil.rmtree(path, onerror=_clear_readonly_and_retry)


def clone_repo(repo_url: str, dest_dir: str, depth: int | None = None, timeout: int = 300) -> str:
    """Clone repo_url into dest_dir and return the path.

    Always clones fresh (any stale dir at dest_dir is removed first) rather
    than reusing a previous clone: a cached shallow clone from an earlier,
    smaller `depth` would silently cap how much history a later, bigger
    request could see. `depth` bounds the fetch to the commits actually
    going to be mined -- for "any public repo" this is what keeps a huge
    project (e.g. the Linux kernel) as fast to track as a small one, instead
    of downloading its entire history just to read the last N commits.
    """
    if os.path.isdir(dest_dir):
        _rmtree(dest_dir)
    os.makedirs(dest_dir, exist_ok=True)
    cmd = ["git", "clone", "--quiet"]
    if depth:
        cmd += ["--depth", str(depth)]
    cmd += [repo_url, dest_dir]
    try:
        subprocess.run(
            cmd,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        _rmtree(dest_dir)
        raise GitOperationError(
            f"Cloning timed out after {timeout}s -- this repository may be too large or unreachable."
        ) from exc
    except subprocess.CalledProcessError as exc:
        _rmtree(dest_dir)
        detail = next((line for line in reversed((exc.stderr or "").splitlines()) if line.strip()), str(exc))
        raise GitOperationError(f"Could not clone this repository: {detail}") from exc
    return dest_dir


def _parse_numstat_body(body: str) -> list[FileChange]:
    """Parse the NUL-delimited --numstat -M body of one commit.

    With `-z`, a normal line is one NUL-terminated token: "<add>\\t<del>\\t<path>\\0".
    A rename line instead leaves the path empty in that first token --
    "<add>\\t<del>\\t\\0" -- immediately followed by two more NUL-terminated
    tokens carrying the old and new paths verbatim (no "{old => new}"
    shorthand, so this never has to guess where an ambiguous rename split).
    Confirmed against real `git log -M --numstat -z` output before writing
    this parser, including a multi-file commit mixing a rename with a plain
    edit, so the token layout below is observed behavior, not a guess from
    the docs.
    """
    tokens = body.split("\x00")
    files: list[FileChange] = []
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok == "":
            i += 1
            continue
        parts = tok.split("\t")
        if len(parts) != 3:
            i += 1
            continue
        add_raw, del_raw, path = parts
        additions = 0 if add_raw == "-" else int(add_raw)
        deletions = 0 if del_raw == "-" else int(del_raw)
        if path == "":
            if i + 2 >= len(tokens):
                break  # truncated output -- stop rather than misread later fields as paths
            old_path, new_path = tokens[i + 1], tokens[i + 2]
            files.append(
                FileChange(path=new_path, additions=additions, deletions=deletions, change_type="R", old_path=old_path)
            )
            i += 3
        else:
            files.append(FileChange(path=path, additions=additions, deletions=deletions, change_type="M"))
            i += 1
    return files


def mine_commits(repo_path: str, max_commits: int, module_depth: int = 1, timeout: int = 300) -> list[Commit]:
    """Run `git log --numstat` on repo_path and parse it into Commit records.

    Rename detection is enabled (`-M`) rather than suppressed: an earlier
    version of this function used --no-renames specifically to dodge a
    parsing hazard -- default numstat output compacts a rename into
    "dir/{old => new}/file.py", ambiguous to split back into two paths, and
    some git installs turn that on even without -M via a global
    diff.renames config. `-z` sidesteps the hazard instead of avoiding
    renames altogether: it makes git emit the old and new paths as two
    separate NUL-terminated fields (see _parse_numstat_body), so renames are
    unambiguous to parse *and* get tracked -- without -z (or with
    --no-renames), a renamed file's pre-rename commit history is silently
    orphaned under the old path once the file mining window is applied.
    """
    # %aN/%aE (mailmap-resolved), not %an/%ae (raw): if the repo ships a
    # .mailmap -- the standard git mechanism for a contributor who has
    # committed under more than one name/email -- this is what makes those
    # commits collapse onto one Author node instead of silently
    # undercounting that person's bus-factor share under each alias.
    fmt = f"{RECORD_SEP}%H{FIELD_SEP}%aN{FIELD_SEP}%aE{FIELD_SEP}%aI{FIELD_SEP}%s"
    try:
        result = subprocess.run(
            [
                "git", "-C", repo_path, "log",
                f"-n{max_commits}",
                "--no-merges",
                "-M",
                "-z",
                "--date=iso-strict",
                f"--pretty=format:{fmt}",
                "--numstat",
            ],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise GitOperationError(f"Mining commit history timed out after {timeout}s.") from exc
    except subprocess.CalledProcessError as exc:
        raise GitOperationError(f"git log failed: {(exc.stderr or str(exc)).strip()}") from exc

    commits: list[Commit] = []
    blocks = result.stdout.split(RECORD_SEP)
    for block in blocks:
        if not block.strip():
            continue
        header, _, body = block.partition("\n")
        fields = header.split(FIELD_SEP)
        if len(fields) != 5:
            continue
        commit_hash, author_name, author_email, timestamp, message = fields
        commit = Commit(
            hash=commit_hash,
            author_name=author_name,
            author_email=author_email or f"{author_name}@unknown.local",
            timestamp=timestamp,
            message=message,
            files=_parse_numstat_body(body),
        )
        if commit.files:
            commits.append(commit)
    return commits


def distinct_files(commits: list[Commit], module_depth: int = 1) -> list[dict]:
    """Every distinct file path touched anywhere in the mined history.

    Loaded as its own pass (see seed/load.py) so each (File, Module,
    BELONGS_TO) triple is written exactly once, rather than re-MERGEd once
    per commit that happens to touch the file -- see the note on
    queries.LOAD_FILES_BATCH for why that distinction matters here.

    A rename's old_path is included too, even though it's never a
    FileChange.path itself: RENAMED_TO edges (see rename_pairs) need a File
    node to exist at the old path to link from, and the old path won't
    otherwise appear here if the commit that created it falls outside this
    mining window.
    """
    seen: dict[str, dict] = {}
    for c in commits:
        for f in c.files:
            if f.path not in seen:
                seen[f.path] = {"path": f.path, "extension": f.extension, "module": f.module(module_depth)}
            if f.old_path and f.old_path not in seen:
                seen[f.old_path] = {
                    "path": f.old_path,
                    "extension": _extension_of(f.old_path),
                    "module": _module_of(f.old_path, module_depth),
                }
    return list(seen.values())


def rename_pairs(commits: list[Commit]) -> list[dict]:
    """Every distinct (old_path -> new_path) rename observed anywhere in the
    mined history, deduplicated for the same reason as distinct_files:
    loaded as its own pass so RENAMED_TO is MERGEd once per pair rather than
    re-merged once per commit that happens to carry it (a file is rarely
    renamed more than once, but nothing stops a rename being reverted and
    redone across history)."""
    seen: dict[tuple[str, str], dict] = {}
    for c in commits:
        for f in c.files:
            if f.old_path:
                key = (f.old_path, f.path)
                if key not in seen:
                    seen[key] = {"from": f.old_path, "to": f.path}
    return list(seen.values())


def list_current_paths(repo_path: str, timeout: int = 60) -> set[str]:
    """File paths that exist in the repo's current HEAD -- used to flag
    File nodes for paths that were deleted at some point in history."""
    try:
        result = subprocess.run(
            ["git", "-C", repo_path, "ls-tree", "-r", "--name-only", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise GitOperationError(f"Listing the current file tree timed out after {timeout}s.") from exc
    except subprocess.CalledProcessError as exc:
        raise GitOperationError(f"git ls-tree failed: {(exc.stderr or str(exc)).strip()}") from exc
    return {line for line in result.stdout.splitlines() if line}


def to_load_records(commits: list[Commit], module_depth: int = 1) -> list[dict]:
    """Shape Commit records into plain dicts ready for the UNWIND batch write."""
    records = []
    for c in commits:
        records.append(
            {
                "hash": c.hash,
                "author_name": c.author_name,
                "author_email": c.author_email,
                "timestamp": c.timestamp,
                "message": c.message[:500],
                "additions": c.additions,
                "deletions": c.deletions,
                "files": [
                    {
                        "path": f.path,
                        "extension": f.extension,
                        "module": f.module(module_depth),
                        "additions": f.additions,
                        "deletions": f.deletions,
                        "change_type": f.change_type,
                    }
                    for f in c.files
                ],
            }
        )
    return records
