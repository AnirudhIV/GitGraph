from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, field_validator

from app import ingest, queries, ratelimit
from app.config import get_settings
from app.db import run_query
from app.schemas import GraphEdge, GraphNode, HotspotOut, RepoMapOut, RepoStatsOut

router = APIRouter()

# A clone+mine+load is the one expensive, unauthenticated thing this API
# does, so it gets its own (tighter) limits on top of the single-job lock in
# app.ingest -- that lock only stops *concurrent* ingests; nothing stops one
# source re-submitting the instant it frees. GLOBAL_INGEST_COOLDOWN throttles
# that regardless of who's asking; INGEST_PER_IP_LIMIT stops one source from
# camping every cooldown window and starving everyone else across cycles.
GLOBAL_INGEST_COOLDOWN_SECONDS = 45
INGEST_PER_IP_LIMIT = 5
INGEST_PER_IP_WINDOW_SECONDS = 3600


class IngestRequest(BaseModel):
    repo_url: str
    max_commits: int = 5000

    @field_validator("repo_url")
    @classmethod
    def validate_repo_url(cls, value: str) -> str:
        value = value.strip()
        if not value.startswith(("http://", "https://")):
            raise ValueError("Enter a public repository URL starting with http:// or https://")
        return value


@router.post("/repo/ingest")
def start_ingest(payload: IngestRequest, request: Request):
    ratelimit.enforce("ingest:global", max_hits=1, window_seconds=GLOBAL_INGEST_COOLDOWN_SECONDS)
    ip = ratelimit.client_ip(request)
    ratelimit.enforce(f"ingest:ip:{ip}", max_hits=INGEST_PER_IP_LIMIT, window_seconds=INGEST_PER_IP_WINDOW_SECONDS)

    max_commits = max(1, min(payload.max_commits, 5000))
    try:
        job_id = ingest.start_job(payload.repo_url, max_commits=max_commits)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"job_id": job_id}


@router.get("/repo/ingest/{job_id}")
def get_ingest_status(job_id: str):
    job = ingest.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Unknown ingest job id.")
    return job


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
    min_commits: int = Query(
        queries.HOTSPOT_DEFAULT_MIN_COMMITS,
        ge=1,
        description="Minimum real churn before a file counts as a hotspot candidate",
    ),
    limit: int = Query(20, ge=1, le=100),
    max_files_per_commit: int = Query(
        queries.HOTSPOT_DEFAULT_MAX_FILES_PER_COMMIT, ge=1, description="Excludes shotgun commits from coupling counts"
    ),
):
    # Risk scores are precomputed at ingest time (seed/load.py::
    # precompute_hotspots) using the same default params as above, so the
    # common case -- every real caller, since the frontend never sends
    # anything else -- is a plain indexed sort with no traversal at request
    # time at all. A caller asking with different params falls back to a
    # live computation: two queries (HOTSPOTS_SIMPLE covers files that were
    # never renamed at the original query cost, HOTSPOTS_ROLLUP pays the
    # rename-lineage-traversal cost only for the minority that need it),
    # merged and re-ranked here. Each is independently sorted and capped at
    # `limit`, so merging the (at most 2 * limit) combined rows before
    # trimming is a correct top-K merge regardless of how the true top
    # results split between the two.
    if min_commits == queries.HOTSPOT_DEFAULT_MIN_COMMITS and max_files_per_commit == queries.HOTSPOT_DEFAULT_MAX_FILES_PER_COMMIT:
        rows = run_query(queries.HOTSPOTS_PRECOMPUTED, {"limit": limit})
    else:
        params = {
            "min_commits": min_commits,
            "limit": limit,
            "max_files_per_commit": max_files_per_commit,
            "half_life_days": get_settings().hotspot_recency_half_life_days,
        }
        rows = run_query(queries.HOTSPOTS_SIMPLE, params) + run_query(queries.HOTSPOTS_ROLLUP, params)
        rows.sort(key=lambda r: r["risk_score"], reverse=True)
        rows = rows[:limit]
    return [
        HotspotOut(
            path=r["path"],
            module=r["module"],
            commit_count=r["commit_count"],
            coupled_file_count=r["coupled_file_count"],
            author_count=r["author_count"],
            coupling_density=round(r["coupling_density"], 3),
            risk_score=round(r["risk_score"], 3),
            risk_score_recent=round(r["risk_score_recent"], 3) if r.get("risk_score_recent") is not None else 0.0,
        )
        for r in rows
    ]


@router.get("/repo/map", response_model=RepoMapOut)
def get_repo_map(
    min_count: int = Query(queries.REPO_FILE_COUPLING_DEFAULT_MIN_COUNT, ge=1),
    limit: int = Query(50, ge=1, le=200),
    max_files_per_commit: int = Query(queries.REPO_FILE_COUPLING_DEFAULT_MAX_FILES_PER_COMMIT, ge=1),
):
    # The repo's strongest file-coupling pairs, unanchored -- a real
    # relationship (the same coupling BLAST_RADIUS_DIRECT shows per-file),
    # not a layout device. An earlier version used module hub nodes with
    # module-identity color, then synthetic per-module star edges once
    # those hubs were dropped for being confusing next to file-risk color;
    # this replaces both with the actual thing blast radius already shows,
    # just repo-wide. Bounded to `limit` pairs, not every file -- that's
    # what keeps the implied node set force-layout-sized regardless of repo
    # size.
    if min_count == queries.REPO_FILE_COUPLING_DEFAULT_MIN_COUNT and max_files_per_commit == (
        queries.REPO_FILE_COUPLING_DEFAULT_MAX_FILES_PER_COMMIT
    ):
        rows = run_query(queries.REPO_FILE_COUPLING_PRECOMPUTED, {"limit": limit})
    else:
        rows = run_query(
            queries.REPO_FILE_COUPLING,
            {"min_count": min_count, "limit": limit, "max_files_per_commit": max_files_per_commit},
        )

    # The node set is whichever files actually appear in the returned
    # pairs -- each pair's own risk_score rides along in the row (see the
    # comment above REPO_FILE_COUPLING), so no second lookup is needed to
    # color/size them the same way Dashboard colors risk.
    risk_by_path: dict[str, float] = {}
    for r in rows:
        risk_by_path[r["path_a"]] = r["risk_score_a"] or 0.0
        risk_by_path[r["path_b"]] = r["risk_score_b"] or 0.0
    max_risk = max(risk_by_path.values(), default=1) or 1

    nodes = [
        GraphNode(
            id=path,
            kind="File",
            label=path.split("/")[-1],
            subtitle=path,
            hop=1,
            weight=round(risk / max_risk, 3),
        )
        for path, risk in risk_by_path.items()
    ]
    edges = [GraphEdge(source=r["path_a"], target=r["path_b"], weight=r["shared_commits"]) for r in rows]
    return RepoMapOut(nodes=nodes, edges=edges)
