"""Mine a real git repository's commit history into structured records.

Shells out to the `git` CLI (no extra dependency) and parses `git log
--numstat` output into commits, each carrying the files it touched. This is
the "real seed data" source for the app -- no synthetic generation involved.
"""
import os
import posixpath
import subprocess
from dataclasses import dataclass, field

RECORD_SEP = "\x1e"
FIELD_SEP = "\x1f"


@dataclass
class FileChange:
    path: str
    additions: int
    deletions: int
    change_type: str  # A (add), M (modify), D (delete) -- best-effort guess

    @property
    def extension(self) -> str:
        _, ext = posixpath.splitext(self.path)
        return ext.lstrip(".").lower()

    def module(self, depth: int) -> str:
        parts = self.path.split("/")
        if len(parts) <= 1:
            return "root"
        return "/".join(parts[:depth]) or "root"


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


def clone_repo(repo_url: str, dest_dir: str) -> str:
    """Clone repo_url into dest_dir (skips if already present) and return the path."""
    if os.path.isdir(os.path.join(dest_dir, ".git")):
        return dest_dir
    os.makedirs(dest_dir, exist_ok=True)
    subprocess.run(
        ["git", "clone", "--quiet", repo_url, dest_dir],
        check=True,
    )
    return dest_dir


def _parse_numstat_line(line: str) -> tuple[int, int, str] | None:
    parts = line.split("\t")
    if len(parts) != 3:
        return None
    add_raw, del_raw, path = parts
    additions = 0 if add_raw == "-" else int(add_raw)
    deletions = 0 if del_raw == "-" else int(del_raw)
    return additions, deletions, path


def mine_commits(repo_path: str, max_commits: int, module_depth: int = 1) -> list[Commit]:
    """Run `git log --numstat` on repo_path and parse it into Commit records.

    Rename detection is explicitly disabled with --no-renames (not just left
    at -M's default of off): some git installs set diff.renames=true in
    global/system config, which turns rename detection on even without -M
    and makes numstat emit "{old => new}" compacted paths -- ambiguous to
    parse and, worse, silently split one file's history into two File nodes
    that only partially connect. --no-renames overrides any such config, so
    renames always show up as a plain delete + add of the full file.
    """
    fmt = f"{RECORD_SEP}%H{FIELD_SEP}%an{FIELD_SEP}%ae{FIELD_SEP}%aI{FIELD_SEP}%s"
    result = subprocess.run(
        [
            "git", "-C", repo_path, "log",
            f"-n{max_commits}",
            "--no-merges",
            "--no-renames",
            "--date=iso-strict",
            f"--pretty=format:{fmt}",
            "--numstat",
        ],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    commits: list[Commit] = []
    blocks = result.stdout.split(RECORD_SEP)
    for block in blocks:
        block = block.strip("\n")
        if not block.strip():
            continue
        lines = block.split("\n")
        header = lines[0]
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
        )
        for line in lines[1:]:
            if not line.strip():
                continue
            parsed = _parse_numstat_line(line)
            if parsed is None:
                continue
            additions, deletions, path = parsed
            change_type = "M"
            commit.files.append(FileChange(path=path, additions=additions, deletions=deletions, change_type=change_type))
        if commit.files:
            commits.append(commit)
    return commits


def distinct_files(commits: list[Commit], module_depth: int = 1) -> list[dict]:
    """Every distinct file path touched anywhere in the mined history.

    Loaded as its own pass (see seed/load.py) so each (File, Module,
    BELONGS_TO) triple is written exactly once, rather than re-MERGEd once
    per commit that happens to touch the file -- see the note on
    queries.LOAD_FILES_BATCH for why that distinction matters here.
    """
    seen: dict[str, dict] = {}
    for c in commits:
        for f in c.files:
            if f.path not in seen:
                seen[f.path] = {"path": f.path, "extension": f.extension, "module": f.module(module_depth)}
    return list(seen.values())


def list_current_paths(repo_path: str) -> set[str]:
    """File paths that exist in the repo's current HEAD -- used to flag
    File nodes for paths that were deleted at some point in history."""
    result = subprocess.run(
        ["git", "-C", repo_path, "ls-tree", "-r", "--name-only", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
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
