"""Seed CognoDB with a repository intelligence graph mined from real git history.

Usage (from the backend/ directory, with .env configured):

    python -m seed.load --repo-url https://github.com/pallets/flask.git --max-commits 1500
    python -m seed.load --repo-path /path/to/existing/clone --max-commits 2000 --clear

Loads in three passes: (1) every distinct File/Module/BELONGS_TO once, from
a deduplicated file list, (2) Author/Commit/AUTHORED/MODIFIED in commit
batches, (3) a pass over the live working tree to flag File nodes whose path
no longer exists at HEAD as deleted. All writes are parameterised,
UNWIND-based batches.
"""
import argparse
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import db, queries  # noqa: E402
from app.config import get_settings  # noqa: E402
from seed.mine_git import clone_repo, distinct_files, list_current_paths, mine_commits, to_load_records  # noqa: E402

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


def load_commits(records: list[dict]) -> None:
    total = len(records)
    print(f"Loading {total} commits in batches of {BATCH_SIZE}...")
    for i in range(0, total, BATCH_SIZE):
        batch = records[i : i + BATCH_SIZE]
        db.run_write(queries.LOAD_COMMIT_BATCH, {"commits": batch})
        print(f"  {min(i + BATCH_SIZE, total)}/{total}")


def mark_deleted(repo_path: str, seen_paths: set[str]) -> None:
    live_paths = list_current_paths(repo_path)
    deleted = sorted(seen_paths - live_paths)
    if not deleted:
        return
    print(f"Marking {len(deleted)} files deleted (no longer present at HEAD)...")
    for i in range(0, len(deleted), BATCH_SIZE):
        db.run_write(queries.MARK_DELETED_FILES, {"paths": deleted[i : i + BATCH_SIZE]})


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repo-url", help="Public git URL to clone (shallow history not used; full clone).")
    parser.add_argument("--repo-path", help="Path to an existing local git clone.")
    parser.add_argument("--max-commits", type=int, default=1500, help="Most recent N commits to import.")
    parser.add_argument("--module-depth", type=int, default=1, help="Path segments used to derive a Module name.")
    parser.add_argument("--clear", action="store_true", help="Wipe the graph before loading.")
    args = parser.parse_args()

    if not args.repo_url and not args.repo_path:
        args.repo_url = "https://github.com/pallets/flask.git"
        print(f"No --repo-url/--repo-path given, defaulting to {args.repo_url}")

    if args.repo_path:
        repo_path = args.repo_path
    else:
        clone_dir = Path(tempfile.gettempdir()) / "repo-graph-seed" / Path(args.repo_url).stem
        print(f"Cloning {args.repo_url} into {clone_dir} ...")
        repo_path = clone_repo(args.repo_url, str(clone_dir))

    print(f"Mining up to {args.max_commits} commits from {repo_path} ...")
    commits = mine_commits(repo_path, args.max_commits, args.module_depth)
    print(f"Parsed {len(commits)} non-merge commits with file changes.")
    if not commits:
        print("Nothing to load -- is this a valid git repo with history?")
        sys.exit(1)

    records = to_load_records(commits, args.module_depth)
    files = distinct_files(commits, args.module_depth)

    settings = get_settings()
    print(f"Connecting to {settings.neo4j_uri} ...")
    db.init_driver()
    try:
        if not db.verify_connectivity():
            print("Could not connect to CognoDB. Check NEO4J_URI/NEO4J_USER/NEO4J_PASSWORD in your .env.")
            sys.exit(1)

        if args.clear:
            wipe_graph()
        ensure_constraints()

        start = time.time()
        load_files(files)
        load_commits(records)
        mark_deleted(repo_path, {f["path"] for f in files})
        elapsed = time.time() - start

        stats = db.run_query(queries.REPO_STATS)
        print(f"\nDone in {elapsed:.1f}s. Graph now has:")
        print(f"  {stats[0]}")
    finally:
        db.close_driver()


if __name__ == "__main__":
    main()
