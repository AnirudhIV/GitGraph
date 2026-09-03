"""`python -m cli ingest <repo-url-or-path>` -- clone (if a URL)/mine/parse
a repo and write its function-level call graph to a local SQLite file.

Deliberately a lighter pipeline than seed/load.py::run_ingest, not a
CognoDB-vs-SQLite fork of the same one: this CLI's schema only ever holds
Function/CALLS/IMPORTS (see cli/storage.py), so there is no File/Module/
Author/Commit graph to load, no CognoDB connectivity check, and no
precompute_* passes. It reuses the identical mining/parsing calls
seed/load.py makes for the pieces that do overlap (mine_commits,
distinct_files, parse_repo, mine_function_change_counts, caller_counts,
compute_risk_score) so the two pipelines can never silently disagree about
what a function's change_count/risk_score is.
"""
import hashlib
import re
import sys
import time
from pathlib import Path
from typing import Callable

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cli import storage  # noqa: E402
from seed.mine_git import (  # noqa: E402
    GitOperationError,
    clone_repo,
    distinct_files,
    mine_commits,
    mine_function_change_counts,
)
from seed.parse import ParseOperationError, caller_counts, compute_risk_score, parse_repo  # noqa: E402

DEFAULT_MAX_COMMITS = 5000

_URL_RE = re.compile(r"^(https?://|git@|ssh://)", re.IGNORECASE)


class IngestError(RuntimeError):
    """Raised when the target can't be cloned/read or has no minable history."""


def _looks_like_url(target: str) -> bool:
    return bool(_URL_RE.match(target)) or target.endswith(".git")


def _clone_dir_name(repo_url: str) -> str:
    name = repo_url.rstrip("/").rsplit("/", 1)[-1]
    if name.endswith(".git"):
        name = name[: -len(".git")]
    return name or hashlib.sha1(repo_url.encode("utf-8")).hexdigest()[:12]


def run_ingest(
    target: str,
    max_commits: int = DEFAULT_MAX_COMMITS,
    module_depth: int = 1,
    clone_timeout: int = 300,
    mine_timeout: int = 300,
    progress: Callable[[str], None] | None = None,
) -> dict:
    """Mine + parse `target` and write the result to `<repo>/.gitgraph/graph.db`.

    A URL target is cloned fresh into ./<repo-name> under the current
    working directory (mirroring `git clone`'s own default destination),
    so the resulting .gitgraph/graph.db ends up somewhere the zero-setup
    read subcommands (which search upward from cwd -- see
    storage.find_db) can actually find it, rather than an ephemeral temp
    directory the caller has no easy path back to. clone_repo always wipes
    an existing directory of that name first (see its own docstring), so
    re-running `cli ingest` on the same URL always re-clones fresh.
    """
    report = progress or print

    if _looks_like_url(target):
        dest_dir = str(Path.cwd() / _clone_dir_name(target))
        report(f"Cloning {target} into {dest_dir} (depth {max_commits}) ...")
        clone_start = time.time()
        try:
            working_path = clone_repo(target, dest_dir, depth=max_commits, timeout=clone_timeout)
        except GitOperationError as exc:
            raise IngestError(str(exc)) from exc
        report(f"Cloned in {time.time() - clone_start:.1f}s.")
    else:
        working_path = str(Path(target).resolve())
        if not (Path(working_path) / ".git").exists():
            raise IngestError(f"'{target}' does not look like a git repository (no .git found).")

    report(f"Mining up to {max_commits} commits ...")
    mine_start = time.time()
    try:
        commits = mine_commits(working_path, max_commits, module_depth, timeout=mine_timeout)
    except GitOperationError as exc:
        raise IngestError(str(exc)) from exc
    report(f"Parsed {len(commits)} non-merge commits in {time.time() - mine_start:.1f}s.")
    if not commits:
        raise IngestError("Nothing to load -- is this a valid git repo with history?")

    files = distinct_files(commits, module_depth)

    report("Parsing functions and call graph ...")
    try:
        parsed = parse_repo(working_path, [f["path"] for f in files])
    except ParseOperationError as exc:
        raise IngestError(f"Function/call graph parsing failed: {exc}") from exc
    for warning in parsed.warnings:
        report(f"Warning: {warning}")

    report("Mining per-function change history ...")
    change_counts = mine_function_change_counts(working_path, parsed.functions)
    callers_by_id = caller_counts(parsed.calls)
    for fn in parsed.functions:
        change_count = change_counts.get(fn["id"], 0)
        caller_count = callers_by_id.get(fn["id"], 0)
        fn["change_count"] = change_count
        fn["risk_score"] = compute_risk_score(change_count, caller_count, fn["complexity"])

    db_file = storage.db_path_for_repo(working_path)
    report(f"Writing {len(parsed.functions)} functions, {len(parsed.calls)} calls, "
           f"{len(parsed.imports)} imports to {db_file} ...")
    conn = storage.init_db(db_file)
    try:
        storage.write_graph(conn, parsed.functions, parsed.calls, parsed.imports)
    finally:
        conn.close()

    return {
        "repo_path": working_path,
        "db_path": str(db_file),
        "commit_count": len(commits),
        "function_count": len(parsed.functions),
        "call_count": len(parsed.calls),
        "import_count": len(parsed.imports),
        "warnings": parsed.warnings,
    }
