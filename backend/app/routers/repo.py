from fastapi import APIRouter, Query

from app import queries
from app.db import run_query
from app.schemas import HotspotOut, RepoStatsOut

router = APIRouter()


@router.get("/stats", response_model=RepoStatsOut)
def get_stats():
    rows = run_query(queries.REPO_STATS)
    row = rows[0] if rows else {}
    return RepoStatsOut(
        file_count=row.get("file_count", 0) or 0,
        commit_count=row.get("commit_count", 0) or 0,
        author_count=row.get("author_count", 0) or 0,
        module_count=row.get("module_count", 0) or 0,
        first_commit_at=row.get("first_ts"),
        last_commit_at=row.get("last_ts"),
    )


@router.get("/hotspots", response_model=list[HotspotOut])
def get_hotspots(
    min_commits: int = Query(8, ge=1, description="Minimum real churn before a file counts as a hotspot candidate"),
    limit: int = Query(20, ge=1, le=100),
    max_files_per_commit: int = Query(10, ge=1, description="Excludes shotgun commits from coupling counts"),
):
    rows = run_query(
        queries.HOTSPOTS,
        {"min_commits": min_commits, "limit": limit, "max_files_per_commit": max_files_per_commit},
    )
    return [
        HotspotOut(
            path=r["path"],
            module=r["module"],
            commit_count=r["commit_count"],
            coupled_file_count=r["coupled_file_count"],
            author_count=r["author_count"],
            coupling_density=round(r["coupling_density"], 3),
            risk_score=round(r["risk_score"], 3),
        )
        for r in rows
    ]
