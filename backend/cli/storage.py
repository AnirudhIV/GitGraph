"""Local SQLite storage for the zero-setup CLI.

Mirrors the Function/CALLS/IMPORTS shape seed/load.py writes to CognoDB
(see app.queries's LOAD_FUNCTIONS_BATCH/LOAD_CALLS_BATCH/LOAD_IMPORTS_BATCH),
but as a single file with no server process and no credentials -- see the
package docstring in cli/__init__.py.

caller_count/callee_count are computed at read time from the `calls` table
(same OPTIONAL-MATCH-and-count shape as app.queries.FUNCTIONS_LIST) rather
than stored as columns -- there is exactly one writer (ingest) and few
enough rows per repo that a COUNT(DISTINCT ...) per lookup is cheap, and
storing it as a column would just be a second place it could go stale.
"""
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

DB_DIRNAME = ".gitgraph"
DB_FILENAME = "graph.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS functions (
    id TEXT PRIMARY KEY,
    path TEXT NOT NULL,
    name TEXT NOT NULL,
    qualname TEXT NOT NULL,
    language TEXT NOT NULL,
    start_line INTEGER NOT NULL,
    end_line INTEGER NOT NULL,
    is_exported INTEGER NOT NULL,
    is_method INTEGER NOT NULL,
    source TEXT NOT NULL,
    change_count INTEGER NOT NULL,
    risk_score REAL NOT NULL,
    complexity INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_functions_path ON functions(path);

CREATE TABLE IF NOT EXISTS calls (
    caller_id TEXT NOT NULL,
    callee_id TEXT NOT NULL,
    confidence TEXT NOT NULL,
    resolution TEXT NOT NULL,
    call_count INTEGER NOT NULL,
    PRIMARY KEY (caller_id, callee_id)
);
CREATE INDEX IF NOT EXISTS idx_calls_callee ON calls(callee_id);
CREATE INDEX IF NOT EXISTS idx_calls_caller ON calls(caller_id);

CREATE TABLE IF NOT EXISTS imports (
    from_path TEXT NOT NULL,
    to_path TEXT NOT NULL,
    imported_names TEXT NOT NULL,
    PRIMARY KEY (from_path, to_path)
);
"""


def db_path_for_repo(repo_path: str) -> Path:
    return Path(repo_path) / DB_DIRNAME / DB_FILENAME


def find_db(start: Path | None = None) -> Path | None:
    """Walk upward from `start` (default: cwd) looking for .gitgraph/graph.db
    -- the same "search upward from where you're standing" convention `git`
    itself uses to find a repo's .git, so a read subcommand run from any
    subdirectory of an ingested repo still finds its local export without
    needing an explicit --db every time."""
    current = (start or Path.cwd()).resolve()
    for candidate in (current, *current.parents):
        db_file = candidate / DB_DIRNAME / DB_FILENAME
        if db_file.is_file():
            return db_file
    return None


@contextmanager
def connect(db_file: Path) -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(str(db_file))
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def init_db(db_file: Path) -> sqlite3.Connection:
    db_file.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_file))
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def write_graph(conn: sqlite3.Connection, functions: list[dict], calls: list[dict], imports: list[dict]) -> None:
    """Replace the whole graph in one transaction.

    Every ingest fully re-derives the current function/call graph from
    source (same "always re-derive, never accumulate" model as
    seed/load.py::wipe_functions -- the CLI has no git-history-append-only
    side to preserve at all), so a wipe-then-insert is the correct rerun
    model here too. Unlike seed/load.py's CognoDB writes (network round
    trips, hence BATCH_SIZE-chunked), this is one local transaction --
    there's no round-trip cost to amortize by chunking it.
    """
    with conn:
        conn.execute("DELETE FROM functions")
        conn.execute("DELETE FROM calls")
        conn.execute("DELETE FROM imports")
        conn.executemany(
            """INSERT INTO functions
               (id, path, name, qualname, language, start_line, end_line,
                is_exported, is_method, source, change_count, risk_score, complexity)
               VALUES (:id, :path, :name, :qualname, :language, :start_line, :end_line,
                       :is_exported, :is_method, :source, :change_count, :risk_score, :complexity)""",
            functions,
        )
        conn.executemany(
            """INSERT INTO calls (caller_id, callee_id, confidence, resolution, call_count)
               VALUES (:caller_id, :callee_id, :confidence, :resolution, :call_count)""",
            calls,
        )
        conn.executemany(
            """INSERT INTO imports (from_path, to_path, imported_names)
               VALUES (:from_path, :to_path, :imported_names)""",
            [{**i, "imported_names": json.dumps(i["imported_names"])} for i in imports],
        )


def _caller_count(conn: sqlite3.Connection, fn_id: str) -> int:
    row = conn.execute("SELECT COUNT(DISTINCT caller_id) AS n FROM calls WHERE callee_id = ?", (fn_id,)).fetchone()
    return row["n"] if row else 0


def _callee_count(conn: sqlite3.Connection, fn_id: str) -> int:
    row = conn.execute("SELECT COUNT(DISTINCT callee_id) AS n FROM calls WHERE caller_id = ?", (fn_id,)).fetchone()
    return row["n"] if row else 0


def function_summary(row: sqlite3.Row, conn: sqlite3.Connection) -> dict[str, Any]:
    return {
        "id": row["id"],
        "name": row["name"],
        "qualname": row["qualname"],
        "path": row["path"],
        "language": row["language"],
        "start_line": row["start_line"],
        "end_line": row["end_line"],
        "is_exported": bool(row["is_exported"]),
        "is_method": bool(row["is_method"]),
        "change_count": row["change_count"],
        "risk_score": row["risk_score"],
        "complexity": row["complexity"],
        "caller_count": _caller_count(conn, row["id"]),
        "callee_count": _callee_count(conn, row["id"]),
    }


def get_function(conn: sqlite3.Connection, fn_id: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM functions WHERE id = ?", (fn_id,)).fetchone()


def search_functions(conn: sqlite3.Connection, query: str, limit: int) -> list[dict]:
    """Plain substring match on qualname/path, filtered in Python rather
    than SQL LIKE: LIKE treats "%"/"_" in the query as wildcards, which
    would silently misbehave for a literal search term containing either
    (not unheard of in a qualname, e.g. a dunder method) -- a repo's
    function count is small enough (low thousands even for a large repo)
    that loading and filtering in Python costs nothing noticeable and
    sidesteps the escaping entirely."""
    needle = query.lower()
    rows = conn.execute("SELECT * FROM functions").fetchall()
    matched = [r for r in rows if needle in r["qualname"].lower() or needle in r["path"].lower()]
    matched.sort(key=lambda r: (-r["risk_score"], r["qualname"]))
    return [function_summary(r, conn) for r in matched[:limit]]


def functions_for_path(conn: sqlite3.Connection, path: str) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM functions WHERE path = ? ORDER BY risk_score DESC", (path,)
    ).fetchall()
    return [function_summary(r, conn) for r in rows]


def call_rows(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "name": row["name"],
        "qualname": row["qualname"],
        "path": row["path"],
        "confidence": row["confidence"],
        "call_count": row["call_count"],
    }


def get_callers(conn: sqlite3.Connection, fn_id: str) -> list[dict]:
    rows = conn.execute(
        """SELECT c.confidence AS confidence, c.call_count AS call_count,
                  f.id AS id, f.name AS name, f.qualname AS qualname, f.path AS path
           FROM calls c JOIN functions f ON f.id = c.caller_id
           WHERE c.callee_id = ?
           ORDER BY c.call_count DESC""",
        (fn_id,),
    ).fetchall()
    return [call_rows(r) for r in rows]


def get_callees(conn: sqlite3.Connection, fn_id: str) -> list[dict]:
    rows = conn.execute(
        """SELECT c.confidence AS confidence, c.call_count AS call_count,
                  f.id AS id, f.name AS name, f.qualname AS qualname, f.path AS path
           FROM calls c JOIN functions f ON f.id = c.callee_id
           WHERE c.caller_id = ?
           ORDER BY c.call_count DESC""",
        (fn_id,),
    ).fetchall()
    return [call_rows(r) for r in rows]
