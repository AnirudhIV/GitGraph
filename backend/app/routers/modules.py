from fastapi import APIRouter, Query

from app import queries
from app.db import run_query
from app.schemas import GraphEdge, GraphNode, ModuleCouplingOut, ModuleGraphOut, ModuleSummaryOut

router = APIRouter()


@router.get("/modules", response_model=list[ModuleSummaryOut])
def list_modules():
    rows = run_query(queries.MODULE_LIST)
    return [
        ModuleSummaryOut(
            name=r["name"],
            file_count=r["file_count"],
            commit_count=r["commit_count"],
            author_count=r["author_count"],
        )
        for r in rows
    ]


@router.get("/modules/coupling", response_model=list[ModuleCouplingOut])
def module_coupling(
    min_count: int = Query(queries.MODULE_COUPLING_DEFAULT_MIN_COUNT, ge=1),
    limit: int = Query(25, ge=1, le=200),
    max_files_per_commit: int = Query(queries.MODULE_COUPLING_DEFAULT_MAX_FILES_PER_COMMIT, ge=1),
):
    # Default params (the only ones the frontend ever sends) read the
    # COUPLED_WITH edges precomputed at ingest time -- see the note above
    # PRECOMPUTE_MODULE_COUPLING in app.queries. Non-default params fall
    # back to a live computation.
    if min_count == queries.MODULE_COUPLING_DEFAULT_MIN_COUNT and max_files_per_commit == (
        queries.MODULE_COUPLING_DEFAULT_MAX_FILES_PER_COMMIT
    ):
        rows = run_query(queries.MODULE_COUPLING_PRECOMPUTED, {"limit": limit})
    else:
        rows = run_query(
            queries.MODULE_COUPLING,
            {"min_count": min_count, "limit": limit, "max_files_per_commit": max_files_per_commit},
        )
    return [
        ModuleCouplingOut(module_a=r["module_a"], module_b=r["module_b"], shared_commits=r["shared_commits"])
        for r in rows
    ]


@router.get("/modules/graph", response_model=ModuleGraphOut)
def module_coupling_graph(
    min_count: int = Query(queries.MODULE_COUPLING_DEFAULT_MIN_COUNT, ge=1),
    limit: int = Query(40, ge=1, le=200),
    max_files_per_commit: int = Query(queries.MODULE_COUPLING_DEFAULT_MAX_FILES_PER_COMMIT, ge=1),
):
    """Same rows as GET /modules/coupling, reshaped as GraphNode/GraphEdge
    for GraphView instead of a flat list -- no new Cypher, just a different
    Python-side projection of the existing coupling query."""
    if min_count == queries.MODULE_COUPLING_DEFAULT_MIN_COUNT and max_files_per_commit == (
        queries.MODULE_COUPLING_DEFAULT_MAX_FILES_PER_COMMIT
    ):
        rows = run_query(queries.MODULE_COUPLING_PRECOMPUTED, {"limit": limit})
    else:
        rows = run_query(
            queries.MODULE_COUPLING,
            {"min_count": min_count, "limit": limit, "max_files_per_commit": max_files_per_commit},
        )

    # A module's node weight is its total coupling activity (summed across
    # every pair it appears in), normalized -- gives bigger bubbles to
    # modules that are more centrally/heavily coupled, the same idea as the
    # weight-by-shared_commits normalization in the blast-radius endpoint.
    total_by_module: dict[str, int] = {}
    for r in rows:
        total_by_module[r["module_a"]] = total_by_module.get(r["module_a"], 0) + r["shared_commits"]
        total_by_module[r["module_b"]] = total_by_module.get(r["module_b"], 0) + r["shared_commits"]
    max_total = max(total_by_module.values(), default=1)

    # hop=1 (not 0): there's no single hub here, every module is a peer, and
    # GraphView's layout gives hop-1 nodes even angular spacing with a gentle
    # centering pull -- the right shape for a peer graph, unlike hop=0's
    # single-dominant-hub pull.
    nodes = [
        GraphNode(id=name, kind="Module", label=name, subtitle=name, hop=1, weight=round(total / max_total, 3))
        for name, total in total_by_module.items()
    ]
    edges = [GraphEdge(source=r["module_a"], target=r["module_b"], weight=r["shared_commits"]) for r in rows]
    return ModuleGraphOut(nodes=nodes, edges=edges)
