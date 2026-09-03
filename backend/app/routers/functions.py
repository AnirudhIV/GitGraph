from typing import Literal

from fastapi import APIRouter, HTTPException, Query

from app import queries
from app.db import run_query
from app.schemas import (
    CallGraphOut,
    FileCallGraphOut,
    FunctionCallOut,
    FunctionDetailOut,
    FunctionListItemOut,
    FunctionMapOut,
    GraphEdge,
    GraphNode,
)

router = APIRouter()

DEFAULT_CALL_LIMIT = 30


@router.get("/functions", response_model=list[FunctionListItemOut])
def list_functions(
    search: str = Query("", description="Substring match on qualname or path"),
    sort: Literal["callers", "risk"] = Query("callers", description="Rank by caller_count or the combined risk_score"),
    limit: int = Query(200, ge=1, le=2000),
):
    query = queries.FUNCTIONS_LIST_BY_RISK if sort == "risk" else queries.FUNCTIONS_LIST
    rows = run_query(query, {"q": search, "limit": limit})
    return [
        FunctionListItemOut(
            id=r["id"],
            name=r["name"],
            qualname=r["qualname"],
            path=r["path"],
            language=r["language"],
            start_line=r["start_line"],
            end_line=r["end_line"],
            is_exported=r["is_exported"],
            is_method=r["is_method"],
            caller_count=r["caller_count"],
            callee_count=r["callee_count"],
            change_count=r["change_count"],
            risk_score=round(r["risk_score"], 3),
        )
        for r in rows
    ]


# Registered before /functions/{id:path} (and before that route's own
# /call-graph variant): "graph" would otherwise be swallowed as a literal
# id by that greedy path converter. Same Starlette-route-ordering hazard
# as files.py's blast-radius route, just against a different sibling route
# this time instead of the bare detail one.
@router.get("/functions/graph", response_model=FunctionMapOut)
def function_map(top_n: int = Query(60, ge=5, le=200), edge_limit: int = Query(150, ge=1, le=500)):
    # Same shape as get_repo_map: rank candidates first, then find edges
    # only among that already-selected set (never the whole graph).
    candidates = run_query(queries.FUNCTION_MAP_CANDIDATES, {"limit": top_n})
    if not candidates:
        return FunctionMapOut(nodes=[], edges=[])

    ids = [c["id"] for c in candidates]
    max_callers = max((c["caller_count"] for c in candidates), default=1) or 1
    nodes = [
        GraphNode(
            id=c["id"],
            kind="Function",
            label=c["name"],
            subtitle=f"{c['path']} - {c['qualname']} - {c['caller_count']} callers",
            hop=1,
            weight=round(c["caller_count"] / max_callers, 3),
            group=c["language"],
        )
        for c in candidates
    ]

    edge_rows = run_query(queries.FUNCTION_MAP_EDGES_AMONG, {"ids": ids, "edge_limit": edge_limit})
    edges = [
        GraphEdge(
            source=r["source"],
            target=r["target"],
            weight=max(1.0, float(r["call_count"] or 1)),
            confidence=r["confidence"] or "high",
        )
        for r in edge_rows
    ]
    return FunctionMapOut(nodes=nodes, edges=edges)


@router.get("/files/{path:path}/functions", response_model=list[FunctionListItemOut])
def list_functions_for_file(path: str):
    rows = run_query(queries.FUNCTIONS_FOR_FILE_WITH_COUNTS, {"path": path})
    return [
        FunctionListItemOut(
            id=r["id"],
            name=r["name"],
            qualname=r["qualname"],
            path=r["path"],
            language=r["language"],
            start_line=r["start_line"],
            end_line=r["end_line"],
            is_exported=r["is_exported"],
            is_method=r["is_method"],
            caller_count=r["caller_count"],
            callee_count=r["callee_count"],
            change_count=r["change_count"],
            risk_score=round(r["risk_score"], 3),
        )
        for r in rows
    ]


@router.get("/files/{path:path}/call-graph", response_model=FileCallGraphOut)
def file_call_graph(path: str):
    functions = run_query(queries.FUNCTIONS_FOR_FILE, {"path": path})
    if not functions:
        return FileCallGraphOut(nodes=[], edges=[])

    nodes = [
        GraphNode(
            id=f["id"],
            kind="Function",
            label=f["name"],
            subtitle=f["qualname"],
            hop=1,
            weight=1.0,
            group=f["language"],
        )
        for f in functions
    ]
    known_ids = {n.id for n in nodes}

    edge_rows = run_query(queries.FILE_CALL_GRAPH_EDGES, {"path": path})
    edges = []
    for r in edge_rows:
        if r["target"] not in known_ids:
            # Cross-file callee: add it as a boundary node (its own path,
            # not expanded further) so the graph shows where a call leaves
            # this file without pulling in that other file's internals.
            nodes.append(
                GraphNode(
                    id=r["target"],
                    kind="Function",
                    label=r["target_name"],
                    subtitle=f"{r['target_path']} - {r['target_qualname']}",
                    hop=2,
                    weight=0.6,
                    group=r["target_language"] or "",
                )
            )
            known_ids.add(r["target"])
        edges.append(
            GraphEdge(
                source=r["source"],
                target=r["target"],
                weight=max(1.0, float(r["call_count"] or 1)),
                confidence=r["confidence"] or "high",
            )
        )

    return FileCallGraphOut(nodes=nodes, edges=edges)


# Registered before /functions/{id:path}: function ids embed the file path
# they're defined in ("{path}::{qualname}"), so id itself contains literal
# "/" characters -- {id:path} has to be a greedy path converter to accept
# that, which means it'd swallow a trailing "/call-graph" too if the plain
# detail route were checked first. Same Starlette-route-ordering hazard
# files.py's blast-radius route comment describes for {path:path}.
@router.get("/functions/{id:path}/call-graph", response_model=CallGraphOut)
def function_call_graph(id: str, depth: int = Query(2, ge=1, le=2), limit: int = Query(12, ge=1, le=50)):
    root_rows = run_query(queries.FUNCTION_DETAIL, {"id": id})
    if not root_rows:
        raise HTTPException(status_code=404, detail=f"No function found with id '{id}'.")
    root = root_rows[0]

    nodes = [
        GraphNode(id=id, kind="Function", label=root["name"], subtitle=f"{root['path']} - {root['qualname']}", hop=0, weight=1.0)
    ]
    edges: list[GraphEdge] = []
    edge_pairs: set[tuple[str, str]] = set()
    seen = {id}

    callees = run_query(queries.FUNCTION_CALL_GRAPH_CALLEES_DIRECT, {"id": id, "limit": limit})
    callers = run_query(queries.FUNCTION_CALL_GRAPH_CALLERS_DIRECT, {"id": id, "limit": limit})
    max_direct = max([c["call_count"] or 1 for c in callees + callers], default=1)

    for r in callees:
        nodes.append(
            GraphNode(id=r["id"], kind="Function", label=r["name"], subtitle=f"{r['path']} - {r['qualname']}", hop=1, weight=round((r["call_count"] or 1) / max_direct, 3))
        )
        edges.append(GraphEdge(source=id, target=r["id"], weight=r["call_count"] or 1, confidence=r["confidence"] or "high"))
        edge_pairs.add((id, r["id"]))
        seen.add(r["id"])
    for r in callers:
        if r["id"] not in seen:
            nodes.append(
                GraphNode(id=r["id"], kind="Function", label=r["name"], subtitle=f"{r['path']} - {r['qualname']}", hop=1, weight=round((r["call_count"] or 1) / max_direct, 3))
            )
            seen.add(r["id"])
        edges.append(GraphEdge(source=r["id"], target=id, weight=r["call_count"] or 1, confidence=r["confidence"] or "high"))
        edge_pairs.add((r["id"], id))

    truncated = False
    if depth == 2 and (callees or callers):
        trans_callees = run_query(queries.FUNCTION_CALL_GRAPH_CALLEES_TRANSITIVE, {"id": id, "limit": limit * 2})
        trans_callers = run_query(queries.FUNCTION_CALL_GRAPH_CALLERS_TRANSITIVE, {"id": id, "limit": limit * 2})
        max_indirect = max([r["call_count"] or 1 for r in trans_callees + trans_callers], default=1)

        for r in trans_callees:
            if r["via"] not in seen:
                continue  # bridge function didn't make the direct set -- no edge to hang this off
            if r["id"] not in seen:
                if len(nodes) >= limit * 2 + 1:
                    truncated = True
                    break
                nodes.append(
                    GraphNode(id=r["id"], kind="Function", label=r["name"], subtitle=f"{r['path']} - {r['qualname']}", hop=2, weight=round((r["call_count"] or 1) / max_indirect, 3))
                )
                seen.add(r["id"])
            pair = (r["via"], r["id"])
            if pair in edge_pairs:
                continue
            edge_pairs.add(pair)
            edges.append(GraphEdge(source=r["via"], target=r["id"], weight=r["call_count"] or 1, confidence=r["confidence"] or "high"))

        for r in trans_callers:
            if r["via"] not in seen:
                continue
            if r["id"] not in seen:
                if len(nodes) >= limit * 2 + 1:
                    truncated = True
                    break
                nodes.append(
                    GraphNode(id=r["id"], kind="Function", label=r["name"], subtitle=f"{r['path']} - {r['qualname']}", hop=2, weight=round((r["call_count"] or 1) / max_indirect, 3))
                )
                seen.add(r["id"])
            pair = (r["id"], r["via"])
            if pair in edge_pairs:
                continue
            edge_pairs.add(pair)
            edges.append(GraphEdge(source=r["id"], target=r["via"], weight=r["call_count"] or 1, confidence=r["confidence"] or "high"))

    return CallGraphOut(root=id, nodes=nodes, edges=edges, truncated=truncated)


@router.get("/functions/{id:path}", response_model=FunctionDetailOut)
def get_function(id: str, caller_limit: int = Query(DEFAULT_CALL_LIMIT, ge=1, le=100), callee_limit: int = Query(DEFAULT_CALL_LIMIT, ge=1, le=100)):
    rows = run_query(queries.FUNCTION_DETAIL, {"id": id})
    if not rows:
        raise HTTPException(status_code=404, detail=f"No function found with id '{id}'.")
    row = rows[0]

    callers = run_query(queries.FUNCTION_CALLERS, {"id": id, "limit": caller_limit})
    callees = run_query(queries.FUNCTION_CALLEES, {"id": id, "limit": callee_limit})

    return FunctionDetailOut(
        id=row["id"],
        name=row["name"],
        qualname=row["qualname"],
        path=row["path"],
        language=row["language"],
        start_line=row["start_line"],
        end_line=row["end_line"],
        is_exported=row["is_exported"],
        is_method=row["is_method"],
        source=row.get("source") or "",
        callers=[
            FunctionCallOut(id=c["id"], name=c["name"], path=c["path"], confidence=c["confidence"], call_count=c["call_count"])
            for c in callers
        ],
        callees=[
            FunctionCallOut(id=c["id"], name=c["name"], path=c["path"], confidence=c["confidence"], call_count=c["call_count"])
            for c in callees
        ],
    )
