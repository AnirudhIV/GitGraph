# gitgraph

Zero-setup, offline function-level risk analysis for git repos. Mines
commit history, parses a real call graph (Python via `ast`, TypeScript/
JavaScript via the TS checker), and scores every function by how often it
changes, how many other functions call it, and how structurally complex it
is -- then writes the result to a single local SQLite file. No server, no
database, no account, no network call after the initial clone.

## Install

```bash
pipx install gitgraph-cli
# or: uvx gitgraph-cli ingest .
```

## Use

```bash
cd your-repo
gitgraph ingest .                 # mines + parses, writes .gitgraph/graph.db
gitgraph search parse_request     # substring match on qualname/path
gitgraph function <id>            # full detail: source, callers, callees
gitgraph callers <id>
gitgraph callees <id>
gitgraph risk path/to/file.py     # every function in a file, by risk_score
gitgraph blast-radius <id> --depth 2
```

Every subcommand after `ingest` is read-only against the local
`.gitgraph/graph.db` (found by searching upward from the current directory,
same convention `git` itself uses for `.git`) and prints JSON to stdout. A
not-found id/path prints `{"error": "..."}` and exits 1, so a script or an
AI coding agent shelling out to this can check the exit code instead of
parsing output for a sentinel key.

Function ids are `{path}::{qualname}` (e.g.
`src/requests/sessions.py::Session.request`) -- pass them as a plain shell
argument, no URL-encoding needed.

## risk_score

`log1p(change_count) * log1p(caller_count) * log1p(complexity)` -- a
function has to be frequently changed *and* widely depended-on *and*
structurally complex to score high. This is a prioritization heuristic
("which touched function deserves a closer look"), not a validated bug
predictor -- see `scripts/validate_risk_score.py` in the main repo for an
honest correlation check against real bug-fix history on a couple of
well-known repos, including where it's weak.

## TS/JS support

Optional. Requires Node.js on PATH plus a one-time
`npm install` in this package's installed `seed/ts-analyzer/` directory
(find it with `python -c "import seed, pathlib; print(pathlib.Path(seed.__file__).parent / 'ts-analyzer')"`).
Without it, `ingest` still works fully for Python files and prints a
warning instead of failing.

## The web dashboard

This package is the CLI only. A separate FastAPI + Neo4j-protocol
dashboard lives in the main repo (`backend/app`, `frontend/`) for teams
who want a shared, browsable view instead of a local file -- see the main
project README.
