"""Zero-setup CLI for GitGraph's function-level call graph.

`python -m cli ingest <repo-url-or-path>` runs the same mining + parsing
pipeline as seed/load.py (seed.mine_git.mine_commits, distinct_files,
seed.parse.parse_repo, seed.mine_git.mine_function_change_counts,
seed.parse.caller_counts) but writes the result to a single local SQLite
file (`.gitgraph/graph.db` in the target repo) instead of CognoDB -- no
server process, no credentials, no network call for every subsequent read.
`python -m cli <subcommand> ...` then reads only from that file.

A wholly separate code path from app/db.py + app/queries.py: this package
never touches CognoDB, and CognoDB-backed ingestion (seed/load.py) never
touches SQLite -- the two storage backends don't know about each other.
"""
