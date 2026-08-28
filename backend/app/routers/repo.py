from typing import Literal

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
    mode: Literal["all-time", "recent"] = Query(
        "all-time", description="Rank and color nodes by risk_score (all-time) or risk_score_recent"
    ),
    top_n: int = Query(40, ge=5, le=100, description="How many risk-ranked files to include"),
    max_files_per_commit: int = Query(
        queries.HOTSPOT_DEFAULT_MAX_FILES_PER_COMMIT, ge=1, description="Excludes shotgun commits from coupling"
    ),
):
    # Risk-first node selection, not coupling-first -- see the comment above
    # REPO_MAP_SOLE_OWNERSHIP in queries.py for why an earlier
    # coupling-pairs-first version could silently drop a genuinely risky
    # file. HOTSPOTS_PRECOMPUTED already ranks every scored file; pull a
    # generous slice and pick the top `top_n` by whichever score `mode`
    # asks for (both ride along on every row already, so the toggle needs
    # no separate query).
    candidates = run_query(queries.HOTSPOTS_PRECOMPUTED, {"limit": max(top_n * 4, 150)})
    score_key = "risk_score" if mode == "all-time" else "risk_score_recent"
    candidates = [c for c in candidates if c.get(score_key) is not None]
    candidates.sort(key=lambda c: c[score_key], reverse=True)
    selected = candidates[:top_n]
    if not selected:
        return RepoMapOut(nodes=[], edges=[])

    paths = [c["path"] for c in selected]
    commit_count_by_path = {c["path"]: c["commit_count"] for c in selected}
    score_by_path = {c["path"]: c[score_key] for c in selected}
    max_score = max(score_by_path.values(), default=1) or 1

    sole_owned = {r["path"] for r in run_query(queries.REPO_MAP_SOLE_OWNERSHIP, {"paths": paths})}
    coupling_rows = run_query(
        queries.REPO_MAP_COUPLING_AMONG, {"paths": paths, "max_files_per_commit": max_files_per_commit}
    )

    nodes = []
    for c in selected:
        path = c["path"]
        risk_score = c.get("risk_score")
        risk_score_recent = c.get("risk_score_recent")
        # A 10% margin so noise around a flat score doesn't read as "trending".
        trending_worse = (
            risk_score is not None and risk_score_recent is not None and risk_score_recent > risk_score * 1.1
        )
        is_sole_owned = path in sole_owned
        subtitle = f"{path} - risk {round(score_by_path[path], 2)}"
        if is_sole_owned:
            subtitle += " - sole-owned"
        if trending_worse:
            subtitle += " - trending up"
        nodes.append(
            GraphNode(
                id=path,
                kind="File",
                label=path.split("/")[-1],
                subtitle=subtitle,
                hop=1,
                weight=round(score_by_path[path] / max_score, 3),
                sole_owned=is_sole_owned,
                trending_worse=trending_worse,
            )
        )

    # Coupling *density* (shared_commits relative to the less-active file's
    # own activity), not a raw count -- see the comment above
    # REPO_MAP_COUPLING_AMONG. Rescaled by 10 so it lands in the same
    # numeric range GraphEdge weights already use elsewhere (raw
    # shared_commits counts), rather than a 0-1 fraction collapsing every
    # edge to the same minimum stroke width in GraphView.
    edges = []
    for r in coupling_rows:
        ca = commit_count_by_path.get(r["path_a"])
        cb = commit_count_by_path.get(r["path_b"])
        if not ca or not cb:
            continue
        density = r["shared_commits"] / min(ca, cb)
        edges.append(GraphEdge(source=r["path_a"], target=r["path_b"], weight=round(density * 10, 2)))

    return RepoMapOut(nodes=nodes, edges=edges)
