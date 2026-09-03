"""Mine a real git repository's commit history into structured records.

Shells out to the `git` CLI (no extra dependency) and parses `git log
--numstat` output into commits, each carrying the files it touched. This is
the "real seed data" source for the app -- no synthetic generation involved.
"""
import os
import posixpath
import re
import shutil
import stat
import subprocess
from collections.abc import Iterator
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


HUNK_HEADER_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@", re.MULTILINE)
# %x01 (git's own pretty-format escape for a literal byte), not a raw \x01
# passed straight into argv -- git's format parser rejects a format string
# that's nothing *but* a literal control byte ("invalid --pretty format"),
# confirmed by hand before landing this; %x01 goes through the format
# engine instead and works. %s (subject) rides along after the mark so
# callers that need to classify a commit (see mine_function_change_history)
# get its message for free, in the same single `git log -p` walk -- git
# guarantees %s never itself contains a newline, so splitting each block on
# the first "\n" cleanly separates the message from the patch that follows.
_COMMIT_MARK_ARG = "--format=%x01%s"
_COMMIT_MARK = "\x01"


def _iter_file_commit_hunks(repo_path: str, path: str, timeout: int) -> Iterator[tuple[str, set[int]]]:
    """Walk one file's non-merge commit history via a single `git log -p`
    subprocess, yielding (commit message, touched new-side line numbers)
    per commit that actually touched a line (a commit whose diff hunks are
    all outside --unified=0's window, e.g. a pure rename with no content
    change, is skipped).

    Shared core behind mine_function_change_counts (churn only) and
    mine_function_change_history (churn + bug-fix classification, see
    Feature 3's scripts/validate_risk_score.py) -- factored out so the two
    mining passes can never disagree about which lines/commits count as
    "touching" a file, and so bug-fix classification doesn't need its own
    second `git log` walk over the same history.
    """
    try:
        result = subprocess.run(
            [
                "git", "-C", repo_path, "log", "--no-merges", "-p", "--unified=0",
                _COMMIT_MARK_ARG,
                "--", path,
            ],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except (subprocess.TimeoutExpired, subprocess.CalledProcessError):
        # One file's history failing to walk (e.g. a path git considers
        # ambiguous) shouldn't lose every other file's change counts.
        return

    for commit_block in result.stdout.split(_COMMIT_MARK)[1:]:
        message, _, patch = commit_block.partition("\n")
        touched_lines: set[int] = set()
        for m in HUNK_HEADER_RE.finditer(patch):
            new_start = int(m.group(1))
            new_count = int(m.group(2)) if m.group(2) is not None else 1
            if new_count == 0:
                # A pure deletion has no new-side lines of its own --
                # attribute it to whatever now occupies that position.
                touched_lines.add(new_start)
            else:
                touched_lines.update(range(new_start, new_start + new_count))
        if touched_lines:
            yield message, touched_lines


def mine_function_change_counts(repo_path: str, functions: list[dict], timeout: int = 120) -> dict[str, int]:
    """For every parsed function (each a dict with id/path/start_line/
    end_line), count the distinct commits whose diff touched a line inside
    that function's current range -- a real per-function churn signal, not
    a file-level proxy (a busy file's quiet helper and its hot entry point
    would otherwise look equally "risky", which defeats the point of
    scoring at function granularity at all).

    Known, accepted approximation (same category of gap as the rename-
    lineage/second-hop notes elsewhere in this file): hunks are matched
    against each function's *current* line range, not the range it
    occupied at the time of that historical commit. As a file's line count
    shifts over time, this can occasionally attribute a commit to the wrong
    neighboring function. `git log -L` resolves this with real tracking
    heuristics; this is a good-enough proxy for "how often has this area of
    the file changed", not a certified per-function blame.

    One `git log` per distinct file (scoped to that file's own path, so git
    itself limits the walk to commits that touched it) rather than one per
    function or one whole-repo diff dump -- bounded by how many files
    actually have functions, not by function or commit count.
    """
    functions_by_path: dict[str, list[dict]] = {}
    for fn in functions:
        functions_by_path.setdefault(fn["path"], []).append(fn)

    change_counts: dict[str, int] = {fn["id"]: 0 for fn in functions}

    for path, fns in functions_by_path.items():
        for _message, touched_lines in _iter_file_commit_hunks(repo_path, path, timeout):
            for fn in fns:
                if any(fn["start_line"] <= ln <= fn["end_line"] for ln in touched_lines):
                    change_counts[fn["id"]] += 1

    return change_counts


# Bug-fix classification heuristic (Feature 3): a conventional-commit `fix:`/
# `fix(scope):` prefix, the standalone words fix/fixes/fixed or bug, or an
# issue reference (#123, and by extension "closes #123"/"fixes #123", which
# already contain a bare #123). Deliberately approximate, not ground truth --
# commit-message conventions vary a lot across projects and authors, so this
# will both miss real fixes described in plain language ("handle empty
# input") and flag some false positives ("fix typo in comment" on a doc-only
# commit). scripts/validate_risk_score.py reports its correlation with that
# caveat front and center rather than presenting bug_fix_count as exact.
_FIX_WORD_RE = re.compile(r"\bfix(?:es|ed)?\b", re.IGNORECASE)
_BUG_WORD_RE = re.compile(r"\bbug\b", re.IGNORECASE)
_ISSUE_REF_RE = re.compile(r"#\d+")
_CONVENTIONAL_FIX_RE = re.compile(r"^fix(?:\([^)]*\))?:", re.IGNORECASE)


def _is_bug_fix_commit(message: str) -> bool:
    return bool(
        _FIX_WORD_RE.search(message)
        or _BUG_WORD_RE.search(message)
        or _ISSUE_REF_RE.search(message)
        or _CONVENTIONAL_FIX_RE.search(message)
    )


def mine_function_change_history(repo_path: str, functions: list[dict], timeout: int = 120) -> dict[str, dict]:
    """Per-function change_count *and* bug_fix_count (distinct bug-fix
    commits -- see _is_bug_fix_commit -- that touched the function), for
    Feature 3's validation of risk_score against real historical bugs.

    Deliberately a sibling of mine_function_change_counts rather than a
    change to its signature/return shape: change_count alone is what
    seed/load.py persists on every ingest (via compute_risk_score), and
    bug_fix_count is only ever needed by the standalone, manually-run
    scripts/validate_risk_score.py -- paying the extra message-
    classification cost (and changing the return shape every existing
    caller depends on) on every ingest isn't worth it for a one-off
    validation pass. Reuses the exact same _iter_file_commit_hunks walk, so
    it agrees with mine_function_change_counts by construction rather than
    by coincidence.
    """
    functions_by_path: dict[str, list[dict]] = {}
    for fn in functions:
        functions_by_path.setdefault(fn["path"], []).append(fn)

    history: dict[str, dict] = {fn["id"]: {"change_count": 0, "bug_fix_count": 0} for fn in functions}

    for path, fns in functions_by_path.items():
        for message, touched_lines in _iter_file_commit_hunks(repo_path, path, timeout):
            is_bug_fix = _is_bug_fix_commit(message)
            for fn in fns:
                if any(fn["start_line"] <= ln <= fn["end_line"] for ln in touched_lines):
                    history[fn["id"]]["change_count"] += 1
                    if is_bug_fix:
                        history[fn["id"]]["bug_fix_count"] += 1

    return history


# Matches the "+++ b/<path>" header unified diff emits immediately before
# that file's own hunks (and "+++ /dev/null" for a deleted file, which has
# no new-side lines to attribute anything to).
_DIFF_NEW_FILE_HEADER_RE = re.compile(r"^\+\+\+ b/(.+)$")


def parse_diff_hunks(diff_text: str) -> dict[str, set[int]]:
    """Map each file touched in a multi-file unified diff (e.g. `git diff
    <base>...HEAD --unified=0`) to the set of new-side line numbers its
    hunks touch -- Feature 4's PR risk-check needs this same "which lines
    changed" signal mine_function_change_counts computes per-commit, just
    applied once across a whole PR diff instead of once per historical
    commit, so this reuses HUNK_HEADER_RE (the same hunk-header regex)
    rather than re-deriving it.

    A single left-to-right scan is sufficient (no need for a real diff
    parser): git always emits a file's "+++ b/<path>" header immediately
    before that file's own hunks, so attributing each hunk to the most
    recently seen path is unambiguous.
    """
    result: dict[str, set[int]] = {}
    current_path: str | None = None
    for line in diff_text.splitlines():
        if line == "+++ /dev/null":
            current_path = None  # deleted file -- nothing to attribute new-side lines to
            continue
        file_match = _DIFF_NEW_FILE_HEADER_RE.match(line)
        if file_match:
            current_path = file_match.group(1)
            result.setdefault(current_path, set())
            continue
        hunk_match = HUNK_HEADER_RE.match(line)
        if hunk_match and current_path is not None:
            new_start = int(hunk_match.group(1))
            new_count = int(hunk_match.group(2)) if hunk_match.group(2) is not None else 1
            if new_count == 0:
                result[current_path].add(new_start)
            else:
                result[current_path].update(range(new_start, new_start + new_count))
    return result


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
