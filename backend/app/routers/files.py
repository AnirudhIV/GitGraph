from fastapi import APIRouter, HTTPException, Query

from app import queries
from app.db import run_query
from app.schemas import (
    BlastRadiusOut,
    CoChangeOut,
    FileDetailOut,
    FileSummaryOut,
    GraphEdge,
    GraphNode,
    OwnerOut,
    RecentCommitOut,
)

router = APIRouter()

# Commits touching more files than this are excluded from coupling
# calculations -- see the note above app.queries.HOTSPOTS_SIMPLE.
DEFAULT_MAX_FILES_PER_COMMIT = 10


@router.get("/files", response_model=list[FileSummaryOut])
def list_files(
    search: str = Query("", description="Substring match on file path"),
    limit: int = Query(50, ge=1, le=500),
):
    rows = run_query(queries.SEARCH_FILES, {"q": search, "limit": limit})
    return [
        FileSummaryOut(
            path=r["path"],
            extension=r["extension"] or "",
            module=r["module"] or "",
            commit_count=r["commit_count"],
            is_deleted=r["is_deleted"],
        )
        for r in rows
    ]


# Registered before /files/{path:path}: Starlette matches path routes in
# registration order, and {path:path} is greedy enough to swallow
# "/blast-radius" too if the plain file-detail route were checked first.
@router.get("/files/{path:path}/blast-radius", response_model=BlastRadiusOut)
def blast_radius(
    path: str,
    depth: int = Query(2, ge=1, le=2),
    min_count: int = Query(2, ge=1),
    limit: int = Query(12, ge=1, le=50),
):
    direct_rows = run_query(
        queries.BLAST_RADIUS_DIRECT,
        {
            "path": path,
            "min_count": min_count,
            "limit": limit,
            "max_files_per_commit": DEFAULT_MAX_FILES_PER_COMMIT,
        },
    )
    nodes = [GraphNode(id=path, kind="File", label=path.split("/")[-1], subtitle=path, hop=0, weight=1.0)]
    edges: list[GraphEdge] = []
    # Co-change coupling is symmetric, so the transitive query below can find
    # the same pair of files as bridges for each other and return it in both
    # directions -- track unordered pairs so that shows up once, not twice.
    edge_pairs: set[frozenset[str]] = set()
    seen = {path}
    max_direct = max((r["shared_commits"] for r in direct_rows), default=1)

    for r in direct_rows:
        nodes.append(
            GraphNode(
                id=r["path"],
                kind="File",
                label=r["path"].split("/")[-1],
                subtitle=r["path"],
                hop=1,
                weight=round(r["shared_commits"] / max_direct, 3),
            )
        )
        edges.append(GraphEdge(source=path, target=r["path"], weight=r["shared_commits"]))
        edge_pairs.add(frozenset((path, r["path"])))
        seen.add(r["path"])

    truncated = False
    if depth == 2 and direct_rows:
        transitive_rows = run_query(
            queries.BLAST_RADIUS_TRANSITIVE,
            {
                "path": path,
                "min_count": min_count,
                "limit": limit * 2,
                "max_files_per_commit": DEFAULT_MAX_FILES_PER_COMMIT,
            },
        )
        max_indirect = max((r["shared_commits"] for r in transitive_rows), default=1)
        for r in transitive_rows:
            if r["via"] not in seen:
                # The bridge file didn't make it into the direct (hop-1) set --
                # e.g. cut off by that query's own limit -- so there's no node
                # for this edge's source. Showing the 2nd-degree file anyway
                # would strand it with no visible path back to the root.
                continue
            if r["path"] not in seen:
                if len(nodes) >= limit * 2 + 1:
                    truncated = True
                    break
                nodes.append(
                    GraphNode(
                        id=r["path"],
                        kind="File",
                        label=r["path"].split("/")[-1],
                        subtitle=r["path"],
                        hop=2,
                        weight=round(r["shared_commits"] / max_indirect, 3),
                    )
                )
                seen.add(r["path"])
            pair = frozenset((r["via"], r["path"]))
            if pair in edge_pairs:
                continue
            edge_pairs.add(pair)
            edges.append(GraphEdge(source=r["via"], target=r["path"], weight=r["shared_commits"]))

    return BlastRadiusOut(root=path, nodes=nodes, edges=edges, truncated=truncated)


@router.get("/files/{path:path}", response_model=FileDetailOut)
def get_file(path: str, recent_limit: int = 15, owner_limit: int = 10, co_change_limit: int = 15):
    rows = run_query(queries.FILE_DETAIL, {"path": path})
    if not rows or rows[0].get("commit_count") is None:
        raise HTTPException(status_code=404, detail=f"No file found at path '{path}'.")
    row = rows[0]

    recent = run_query(queries.FILE_RECENT_COMMITS, {"path": path, "limit": recent_limit})
    owners = run_query(queries.FILE_OWNERS, {"path": path, "limit": owner_limit})
    co_changes = run_query(
        queries.FILE_CO_CHANGES,
        {
            "path": path,
            "min_count": 1,
            "limit": co_change_limit,
            "max_files_per_commit": DEFAULT_MAX_FILES_PER_COMMIT,
        },
    )

    return FileDetailOut(
        path=row["path"],
        extension=row["extension"] or "",
        module=row["module"] or "",
        is_deleted=row["is_deleted"],
        renamed_to=row.get("renamed_to"),
        commit_count=row["commit_count"],
        first_commit_at=row["first_ts"],
        last_commit_at=row["last_ts"],
        risk_score=round(row["risk_score"], 3) if row.get("risk_score") is not None else None,
        risk_score_recent=round(row["risk_score_recent"], 3) if row.get("risk_score_recent") is not None else None,
        recent_commits=[
            RecentCommitOut(
                hash=c["hash"],
                message=c["message"],
                author_name=c["author_name"],
                timestamp=c["timestamp"],
                additions=c["additions"] or 0,
                deletions=c["deletions"] or 0,
            )
            for c in recent
        ],
        owners=[
            OwnerOut(
                author_name=o["author_name"],
                author_email=o["author_email"],
                commit_count=o["commit_count"],
                share=round(o["share"], 3),
            )
            for o in owners
        ],
        co_changes=[
            CoChangeOut(path=c["path"], module=c["module"] or "", shared_commits=c["shared_commits"])
            for c in co_changes
        ],
    )
