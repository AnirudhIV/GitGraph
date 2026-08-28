"""Seed CognoDB with a repository intelligence graph mined from real git history.

Usage (from the backend/ directory, with .env configured):

    python -m seed.load --repo-url https://github.com/pallets/flask.git --max-commits 5000
    python -m seed.load --repo-path /path/to/existing/clone --max-commits 2000 --clear

Loads in passes: (1) every distinct File/Module/BELONGS_TO once, from a
deduplicated file list, (2) RENAMED_TO edges, (3) Author/Commit/AUTHORED/
MODIFIED in commit batches, (4) a pass over the live working tree to flag
File nodes whose path no longer exists at HEAD as deleted, (5) hotspot risk
scores precomputed once and stored on each File node rather than recomputed
per dashboard load. All writes are parameterised, UNWIND-based batches.
"""
import argparse
import hashlib
import sys
import tempfile
import time
from pathlib import Path
from typing import Callable

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import db, queries  # noqa: E402
from app.config import get_settings  # noqa: E402
from seed.mine_git import (  # noqa: E402
    GitOperationError,
    clone_repo,
    distinct_files,
    list_current_paths,
    mine_commits,
    rename_pairs,
    to_load_records,
)

BATCH_SIZE = 250


def wipe_graph() -> None:
    print("Clearing existing graph data...")
    total = 0
    while True:
        rows = db.run_write(queries.WIPE_BATCH, {"batch_size": 5000})
        deleted = rows[0]["deleted"] if rows else 0
        total += deleted
        if deleted == 0:
            break
    print(f"  deleted {total} nodes.")


def ensure_constraints() -> None:
    print("Ensuring constraints/indexes exist...")
    for stmt in queries.CONSTRAINTS:
        db.run_write(stmt)


def load_files(files: list[dict]) -> None:
    total = len(files)
    print(f"Loading {total} distinct files in batches of {BATCH_SIZE}...")
    for i in range(0, total, BATCH_SIZE):
        batch = files[i : i + BATCH_SIZE]
        db.run_write(queries.LOAD_FILES_BATCH, {"files": batch})
        print(f"  {min(i + BATCH_SIZE, total)}/{total}")


def load_renames(renames: list[dict]) -> None:
    if not renames:
        return
    total = len(renames)
    print(f"Loading {total} renames in batches of {BATCH_SIZE}...")
    for i in range(0, total, BATCH_SIZE):
        batch = renames[i : i + BATCH_SIZE]
        db.run_write(queries.LOAD_RENAMES_BATCH, {"renames": batch})
        print(f"  {min(i + BATCH_SIZE, total)}/{total}")


def load_commits(records: list[dict]) -> None:
    total = len(records)
    print(f"Loading {total} commits in batches of {BATCH_SIZE}...")
    for i in range(0, total, BATCH_SIZE):
        batch = records[i : i + BATCH_SIZE]
        db.run_write(queries.LOAD_COMMIT_BATCH, {"commits": batch})
        print(f"  {min(i + BATCH_SIZE, total)}/{total}")


def precompute_hotspots(
    min_commits: int = queries.HOTSPOT_DEFAULT_MIN_COMMITS,
    max_files_per_commit: int = queries.HOTSPOT_DEFAULT_MAX_FILES_PER_COMMIT,
    half_life_days: float | None = None,
) -> None:
    """Compute and store risk_score/risk_score_recent/hotspot_* on every
    qualifying File node.

    GET /api/hotspots used to run this computation fresh on every request,
    but the graph only changes on a re-track -- a write-once-read-many
    workload, so this pays the (real, measured) traversal cost once here
    instead of on every dashboard load. Only ever called with the default
    params (the frontend never sends others); see the note on
    HOTSPOT_DEFAULT_MIN_COMMITS in app.queries for what happens if an API
    caller asks with different ones.
    """
    if half_life_days is None:
        half_life_days = get_settings().hotspot_recency_half_life_days
    params = {"min_commits": min_commits, "max_files_per_commit": max_files_per_commit, "half_life_days": half_life_days}
    db.run_write(queries.PRECOMPUTE_HOTSPOTS_SIMPLE, params)
    db.run_write(queries.PRECOMPUTE_HOTSPOTS_ROLLUP, params)


def precompute_author_stats() -> None:
    """Compute and store commit_count/file_count/first_commit_at/
    last_commit_at on every Author node -- same write-once-read-many
    reasoning as precompute_hotspots, for the no-search-term case of
    GET /api/authors (the only one the frontend hits on first load)."""
    db.run_write(queries.PRECOMPUTE_AUTHOR_STATS)


def precompute_module_coupling(
    min_count: int = queries.MODULE_COUPLING_DEFAULT_MIN_COUNT,
    max_files_per_commit: int = queries.MODULE_COUPLING_DEFAULT_MAX_FILES_PER_COMMIT,
) -> None:
    """Compute and store each module pair's coupling as a COUPLED_WITH edge
    -- same write-once-read-many reasoning as precompute_hotspots."""
    params = {"min_count": min_count, "max_files_per_commit": max_files_per_commit}
    db.run_write(queries.PRECOMPUTE_MODULE_COUPLING, params)


def precompute_repo_file_coupling(
    min_count: int = queries.REPO_FILE_COUPLING_DEFAULT_MIN_COUNT,
    max_files_per_commit: int = queries.REPO_FILE_COUPLING_DEFAULT_MAX_FILES_PER_COMMIT,
) -> None:
    """Compute and store the repo's strongest file-to-file coupling pairs as
    COUPLED_WITH edges between File nodes -- backs GET /repo/map. Same
    write-once-read-many reasoning, and the same traversal shape, as
    precompute_module_coupling, just one level down."""
    params = {"min_count": min_count, "max_files_per_commit": max_files_per_commit}
    db.run_write(queries.PRECOMPUTE_REPO_FILE_COUPLING, params)


def mark_deleted(repo_path: str, seen_paths: set[str], progress: Callable[[str], None] | None = None) -> None:
    report = progress or print
    try:
        live_paths = list_current_paths(repo_path)
    except GitOperationError as exc:
        # Everything that matters (files/commits/authors) is already loaded
        # by this point -- losing the is_deleted flag on stale paths is a
        # cosmetic gap, not worth failing an otherwise-successful ingest.
        report(f"Warning: couldn't check for deleted files ({exc}); skipping.")
        return
    deleted = sorted(seen_paths - live_paths)
    if not deleted:
        return
    report(f"Marking {len(deleted)} files deleted (no longer present at HEAD)...")
    for i in range(0, len(deleted), BATCH_SIZE):
        db.run_write(queries.MARK_DELETED_FILES, {"paths": deleted[i : i + BATCH_SIZE]})


class IngestError(RuntimeError):
    """Raised when a repository can't be cloned or has no minable history."""


def run_ingest(
    repo_url: str | None = None,
    repo_path: str | None = None,
    max_commits: int = 5000,
    module_depth: int = 1,
    clear: bool = True,
    progress: Callable[[str], None] | None = None,
    clone_timeout: int = 300,
    mine_timeout: int = 300,
) -> dict:
    """Clone (if needed), mine, and load a repository into CognoDB.

    Shared by the CLI entrypoint below and the API's background ingest job,
    so both paths clone/mine/load exactly the same way. `clone_timeout` /
    `mine_timeout` bound the two subprocess phases: since this is reachable
    from an unauthenticated API that accepts any public repo URL, an
    unreachable host or a pathologically large repo must fail within a
    fixed budget rather than hang the caller (and the single-ingest-at-a-
    time lock in app.ingest) indefinitely.
    """
    report = progress or print

    if repo_path:
        working_path = repo_path
    else:
        assert repo_url is not None
        # Hash the URL rather than using Path(repo_url).stem: two different
        # repos can share a stem (e.g. .../a/foo.git and .../b/foo.git),
        # which would otherwise collide on the same clone directory and
        # silently mine the wrong repo's working tree.
        digest = hashlib.sha1(repo_url.encode("utf-8")).hexdigest()[:16]
        clone_dir = Path(tempfile.gettempdir()) / "repo-graph-seed" / digest
        report(f"Cloning {repo_url} (depth {max_commits}) ...")
        clone_start = time.time()
        try:
            # depth=max_commits: only fetch the history we're actually
            # going to mine, so a huge repo's full history is never
            # downloaded just to read its last N commits.
            working_path = clone_repo(repo_url, str(clone_dir), depth=max_commits, timeout=clone_timeout)
        except GitOperationError as exc:
            raise IngestError(str(exc)) from exc
        report(f"Cloned in {time.time() - clone_start:.1f}s.")

    report(f"Mining up to {max_commits} commits ...")
    mine_start = time.time()
    try:
        commits = mine_commits(working_path, max_commits, module_depth, timeout=mine_timeout)
    except GitOperationError as exc:
        raise IngestError(str(exc)) from exc
    report(f"Parsed {len(commits)} non-merge commits in {time.time() - mine_start:.1f}s.")
    if not commits:
        raise IngestError("Nothing to load -- is this a valid git repo with history?")

    records = to_load_records(commits, module_depth)
    files = distinct_files(commits, module_depth)
    renames = rename_pairs(commits)

    if not db.verify_connectivity():
        raise IngestError("Could not connect to CognoDB. Check NEO4J_URI/NEO4J_USER/NEO4J_PASSWORD in your .env.")

    if clear:
        report("Clearing existing graph data...")
        wipe_graph()
    report("Ensuring constraints/indexes exist...")
    ensure_constraints()

    load_start = time.time()
    report(f"Loading {len(files)} distinct files...")
    load_files(files)
    if renames:
        report(f"Loading {len(renames)} renames...")
        load_renames(renames)
    report(f"Loading {len(records)} commits...")
    load_commits(records)
    mark_deleted(working_path, {f["path"] for f in files}, progress=report)
    report("Precomputing hotspot risk scores...")
    precompute_hotspots()
    report("Precomputing author stats...")
    precompute_author_stats()
    report("Precomputing module coupling...")
    precompute_module_coupling()
    report("Precomputing repo-wide file coupling...")
    precompute_repo_file_coupling()
    report(f"Loaded graph in {time.time() - load_start:.1f}s.")

    stats = db.run_query(queries.REPO_STATS)
    return stats[0] if stats else {}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repo-url", help="Public git URL to clone (shallow clone, depth = --max-commits).")
    parser.add_argument("--repo-path", help="Path to an existing local git clone.")
    parser.add_argument("--max-commits", type=int, default=5000, help="Most recent N commits to import.")
    parser.add_argument("--module-depth", type=int, default=1, help="Path segments used to derive a Module name.")
    parser.add_argument("--clear", action="store_true", help="Wipe the graph before loading.")
    args = parser.parse_args()

    if not args.repo_url and not args.repo_path:
        args.repo_url = "https://github.com/pallets/flask.git"
        print(f"No --repo-url/--repo-path given, defaulting to {args.repo_url}")

    settings = get_settings()
    print(f"Connecting to {settings.neo4j_uri} ...")
    db.init_driver()
    try:
        stats = run_ingest(
            repo_url=args.repo_url,
            repo_path=args.repo_path,
            max_commits=args.max_commits,
            module_depth=args.module_depth,
            clear=args.clear,
        )
        print(f"\nGraph now has:\n  {stats}")
    except IngestError as exc:
        print(str(exc))
        sys.exit(1)
    finally:
        db.close_driver()


if __name__ == "__main__":
    main()
