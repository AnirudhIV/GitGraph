from fastapi import APIRouter, Query

from app import queries
from app.db import run_query
from app.schemas import ModuleCouplingOut, ModuleSummaryOut

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
