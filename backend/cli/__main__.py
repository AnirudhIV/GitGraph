"""Entry point: `gitgraph <subcommand> ...` once installed (`pipx install
gitgraph-cli`, see backend/pyproject.toml's [project.scripts]) -- or, from
a source checkout with no install, `python -m cli <subcommand> ...` run
from the backend/ directory (same convention as `python -m seed.load`).
Both resolve to the same `main()` below.

`ingest` writes to a local SQLite file (see cli/ingest.py, cli/storage.py);
every other subcommand is read-only against that file, printing one JSON
document to stdout. On a not-found id/path, the JSON document is
`{"error": "..."}` and the process exits 1 -- so a calling agent can detect
failure from the exit code alone, without having to parse the output for a
sentinel key that a legitimate result could theoretically also contain.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cli import storage  # noqa: E402
from cli.ingest import IngestError, run_ingest  # noqa: E402

DEFAULT_SEARCH_LIMIT = 50
# One hop's fan-out cap on each side of a blast-radius, direct and
# transitive alike -- same bounded-fan-out idiom as app.queries's
# FUNCTION_CALL_GRAPH_*_DIRECT/TRANSITIVE (ORDER BY call_count DESC LIMIT),
# so a hub function's blast radius stays a readable graph instead of
# dumping its entire, possibly huge, neighborhood.
BLAST_RADIUS_LIMIT = 30


def _error(message: str) -> None:
    print(json.dumps({"error": message}))
    sys.exit(1)


def _open_db(explicit: str | None) -> storage.sqlite3.Connection:
    db_file = Path(explicit).resolve() if explicit else storage.find_db()
    if db_file is None or not Path(db_file).is_file():
        _error(
            "No .gitgraph/graph.db found (searched upward from the current directory). "
            "Run `python -m cli ingest <repo-url-or-path>` first, or pass --db explicitly."
        )
    conn = storage.sqlite3.connect(str(db_file))
    conn.row_factory = storage.sqlite3.Row
    return conn


def cmd_ingest(args: argparse.Namespace) -> None:
    try:
        result = run_ingest(
            args.target,
            max_commits=args.max_commits,
            module_depth=args.module_depth,
            progress=lambda msg: print(msg, file=sys.stderr),
        )
    except IngestError as exc:
        _error(str(exc))
        return
    print(json.dumps(result, indent=2))


def cmd_search(args: argparse.Namespace) -> None:
    conn = _open_db(args.db)
    results = storage.search_functions(conn, args.query, args.limit)
    print(json.dumps(results, indent=2))


def cmd_function(args: argparse.Namespace) -> None:
    conn = _open_db(args.db)
    row = storage.get_function(conn, args.id)
    if row is None:
        _error(f"No function found with id '{args.id}'.")
        return
    detail = storage.function_summary(row, conn)
    detail["source"] = row["source"]
    detail["callers"] = storage.get_callers(conn, args.id)
    detail["callees"] = storage.get_callees(conn, args.id)
    print(json.dumps(detail, indent=2))


def cmd_callers(args: argparse.Namespace) -> None:
    conn = _open_db(args.db)
    if storage.get_function(conn, args.id) is None:
        _error(f"No function found with id '{args.id}'.")
        return
    print(json.dumps(storage.get_callers(conn, args.id), indent=2))


def cmd_callees(args: argparse.Namespace) -> None:
    conn = _open_db(args.db)
    if storage.get_function(conn, args.id) is None:
        _error(f"No function found with id '{args.id}'.")
        return
    print(json.dumps(storage.get_callees(conn, args.id), indent=2))


def cmd_risk(args: argparse.Namespace) -> None:
    conn = _open_db(args.db)
    results = storage.functions_for_path(conn, args.path)
    if not results:
        _error(f"No functions found for path '{args.path}'.")
        return
    print(json.dumps(results, indent=2))


def cmd_blast_radius(args: argparse.Namespace) -> None:
    conn = _open_db(args.db)
    root = storage.get_function(conn, args.id)
    if root is None:
        _error(f"No function found with id '{args.id}'.")
        return

    nodes: dict[str, dict] = {
        args.id: {"id": args.id, "name": root["name"], "qualname": root["qualname"], "path": root["path"], "hop": 0}
    }
    edges: list[dict] = []
    edge_pairs: set[tuple[str, str]] = set()

    callees = storage.get_callees(conn, args.id)[:BLAST_RADIUS_LIMIT]
    callers = storage.get_callers(conn, args.id)[:BLAST_RADIUS_LIMIT]

    for c in callees:
        nodes.setdefault(c["id"], {"id": c["id"], "name": c["name"], "qualname": c["qualname"], "path": c["path"], "hop": 1})
        pair = (args.id, c["id"])
        if pair not in edge_pairs:
            edge_pairs.add(pair)
            edges.append({"source": args.id, "target": c["id"], "call_count": c["call_count"], "confidence": c["confidence"]})
    for c in callers:
        nodes.setdefault(c["id"], {"id": c["id"], "name": c["name"], "qualname": c["qualname"], "path": c["path"], "hop": 1})
        pair = (c["id"], args.id)
        if pair not in edge_pairs:
            edge_pairs.add(pair)
            edges.append({"source": c["id"], "target": args.id, "call_count": c["call_count"], "confidence": c["confidence"]})

    truncated = False
    max_nodes = BLAST_RADIUS_LIMIT * 2 + 1

    def _add_transitive(bridge_id: str, neighbor: dict, edge: tuple[str, str]) -> bool:
        """Wire in one transitive neighbor; returns False once the node cap
        is hit so the caller can stop scanning entirely rather than just
        breaking its own inner loop (a plain `break` here would still let
        a later bridge's loop keep adding nodes past the cap)."""
        nonlocal truncated
        if neighbor["id"] == args.id or (neighbor["id"] in nodes and nodes[neighbor["id"]]["hop"] < 2):
            return True
        if len(nodes) >= max_nodes:
            truncated = True
            return False
        nodes.setdefault(
            neighbor["id"],
            {"id": neighbor["id"], "name": neighbor["name"], "qualname": neighbor["qualname"], "path": neighbor["path"], "hop": 2},
        )
        if edge not in edge_pairs:
            edge_pairs.add(edge)
            src, dst = edge
            edges.append({"source": src, "target": dst, "call_count": neighbor["call_count"], "confidence": neighbor["confidence"]})
        return True

    if args.depth == 2:
        # One transitive hop past the direct set, same "bridge must already
        # be in the seen set" idiom as app.routers.functions.function_call_graph:
        # a transitive neighbor is only wired in via the direct-hop bridge
        # that actually made this blast radius, not via any path to it.
        stop = False
        for c in callees:
            if stop:
                break
            for cc in storage.get_callees(conn, c["id"])[:BLAST_RADIUS_LIMIT]:
                if not _add_transitive(c["id"], cc, (c["id"], cc["id"])):
                    stop = True
                    break
        stop = False
        for c in callers:
            if stop:
                break
            for cc in storage.get_callers(conn, c["id"])[:BLAST_RADIUS_LIMIT]:
                if not _add_transitive(c["id"], cc, (cc["id"], c["id"])):
                    stop = True
                    break

    print(json.dumps({"root": args.id, "nodes": list(nodes.values()), "edges": edges, "truncated": truncated}, indent=2))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="gitgraph", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    p_ingest = sub.add_parser("ingest", help="Mine + parse a repo and write its call graph to .gitgraph/graph.db")
    p_ingest.add_argument("target", help="Git URL to clone, or a path to an existing local clone")
    p_ingest.add_argument("--max-commits", type=int, default=5000)
    p_ingest.add_argument("--module-depth", type=int, default=1)
    p_ingest.set_defaults(func=cmd_ingest)

    p_search = sub.add_parser("search", help="Substring match on qualname/path")
    p_search.add_argument("query")
    p_search.add_argument("--limit", type=int, default=DEFAULT_SEARCH_LIMIT)
    p_search.add_argument("--db", help="Path to graph.db (default: search upward from cwd)")
    p_search.set_defaults(func=cmd_search)

    p_function = sub.add_parser("function", help="Full detail for one function id")
    p_function.add_argument("id")
    p_function.add_argument("--db")
    p_function.set_defaults(func=cmd_function)

    p_callers = sub.add_parser("callers", help="Callers of one function id")
    p_callers.add_argument("id")
    p_callers.add_argument("--db")
    p_callers.set_defaults(func=cmd_callers)

    p_callees = sub.add_parser("callees", help="Callees of one function id")
    p_callees.add_argument("id")
    p_callees.add_argument("--db")
    p_callees.set_defaults(func=cmd_callees)

    p_risk = sub.add_parser("risk", help="Every function in a file, sorted by risk_score")
    p_risk.add_argument("path")
    p_risk.add_argument("--db")
    p_risk.set_defaults(func=cmd_risk)

    p_blast = sub.add_parser("blast-radius", help="Rooted call graph, both directions")
    p_blast.add_argument("id")
    p_blast.add_argument("--depth", type=int, choices=[1, 2], default=1)
    p_blast.add_argument("--db")
    p_blast.set_defaults(func=cmd_blast_radius)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
