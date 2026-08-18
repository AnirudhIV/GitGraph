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
    min_count: int = Query(2, ge=1),
    limit: int = Query(25, ge=1, le=200),
    max_files_per_commit: int = Query(10, ge=1),
):
    rows = run_query(
        queries.MODULE_COUPLING,
        {"min_count": min_count, "limit": limit, "max_files_per_commit": max_files_per_commit},
    )
    return [
        ModuleCouplingOut(module_a=r["module_a"], module_b=r["module_b"], shared_commits=r["shared_commits"])
        for r in rows
    ]
