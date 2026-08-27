from fastapi import APIRouter, HTTPException, Query

from app import queries
from app.db import run_query
from app.schemas import (
    AuthorDetailOut,
    AuthorFileOut,
    AuthorNetworkOut,
    AuthorSummaryOut,
    CollabPathOut,
    CollabPathStepOut,
    GraphEdge,
    GraphNode,
    SuccessionFileOut,
)

router = APIRouter()

# Caps how many of the anchor author's own files (ranked by their commit
# count on each) seed the collaboration-network query -- see the note above
# app.queries.AUTHOR_NETWORK for why an unbounded scan over a prolific
# author's full file list was measured at 8s+.
AUTHOR_NETWORK_MAX_ANCHOR_FILES = 80


@router.get("/authors", response_model=list[AuthorSummaryOut])
def list_authors(search: str = Query(""), limit: int = Query(30, ge=1, le=200), offset: int = 0):
    # No search term (the only case on first page load) reads precomputed
    # stats directly -- no aggregation at request time. An actual search
    # term can't be precomputed (arbitrary input), so it falls back to
    # AUTHOR_LIST, which filters by name before aggregating rather than
    # after -- see the note above PRECOMPUTE_AUTHOR_STATS in app.queries.
    if search == "":
        rows = run_query(queries.AUTHOR_LIST_PRECOMPUTED, {"limit": limit, "offset": offset})
    else:
        rows = run_query(queries.AUTHOR_LIST, {"search": search, "limit": limit, "offset": offset})
    return [
        AuthorSummaryOut(
            email=r["email"],
            name=r["name"],
            commit_count=r["commit_count"],
            file_count=r["file_count"],
            first_commit_at=r["first_ts"],
            last_commit_at=r["last_ts"],
        )
        for r in rows
    ]


@router.get("/authors/path", response_model=CollabPathOut)
def collaboration_path(email_a: str, email_b: str):
    if email_a == email_b:
        raise HTTPException(status_code=400, detail="Pick two different authors.")

    direct = run_query(queries.AUTHOR_DIRECT_CONNECTION, {"email_a": email_a, "email_b": email_b})
    if direct:
        r = direct[0]
        steps = [
            CollabPathStepOut(kind="Author", id=r["a1_email"], label=r["a1_name"]),
            CollabPathStepOut(kind="File", id=r["file_path"], label=r["file_path"]),
            CollabPathStepOut(kind="Author", id=r["a2_email"], label=r["a2_name"]),
        ]
        return CollabPathOut(found=True, hops=len(steps) - 1, steps=steps)

    bridge = run_query(queries.AUTHOR_BRIDGE_CONNECTION, {"email_a": email_a, "email_b": email_b})
    if bridge:
        r = bridge[0]
        steps = [
            CollabPathStepOut(kind="Author", id=r["a1_email"], label=r["a1_name"]),
            CollabPathStepOut(kind="File", id=r["file_path_1"], label=r["file_path_1"]),
            CollabPathStepOut(kind="Author", id=r["bridge_email"], label=r["bridge_name"]),
            CollabPathStepOut(kind="File", id=r["file_path_2"], label=r["file_path_2"]),
            CollabPathStepOut(kind="Author", id=r["a2_email"], label=r["a2_name"]),
        ]
        return CollabPathOut(found=True, hops=len(steps) - 1, steps=steps)

    return CollabPathOut(found=False, hops=0, steps=[])


@router.get("/authors/{email}/network", response_model=AuthorNetworkOut)
def author_network(email: str, min_shared: int = Query(1, ge=1), limit: int = Query(15, ge=1, le=50)):
    anchor_rows = run_query(queries.AUTHOR_DETAIL, {"email": email})
    if not anchor_rows or anchor_rows[0].get("commit_count") is None:
        raise HTTPException(status_code=404, detail=f"No author found with email '{email}'.")
    anchor = anchor_rows[0]

    neighbor_rows = run_query(
        queries.AUTHOR_NETWORK,
        {
            "email": email,
            "min_shared": min_shared,
            "limit": limit,
            "max_anchor_files": AUTHOR_NETWORK_MAX_ANCHOR_FILES,
        },
    )
    max_shared = max((r["shared_files"] for r in neighbor_rows), default=1)
    nodes = [GraphNode(id=email, kind="Author", label=anchor["name"], subtitle=email, hop=0, weight=1.0)]
    edges: list[GraphEdge] = []
    for r in neighbor_rows:
        nodes.append(
            GraphNode(
                id=r["email"],
                kind="Author",
                label=r["name"],
                subtitle=f"{r['shared_files']} shared file{'s' if r['shared_files'] != 1 else ''}",
                hop=1,
                weight=round(r["shared_files"] / max_shared, 3),
            )
        )
        edges.append(GraphEdge(source=email, target=r["email"], weight=r["shared_files"]))

    at_risk_rows = run_query(queries.AUTHOR_SOLE_OWNED_FILES, {"email": email, "limit": 15})

    return AuthorNetworkOut(
        root=email,
        nodes=nodes,
        edges=edges,
        at_risk_files=[
            SuccessionFileOut(
                path=r["path"],
                module=r["module"] or "",
                commit_count=r["commit_count"],
                last_touched=r["last_touched"],
            )
            for r in at_risk_rows
        ],
    )


@router.get("/authors/{email}", response_model=AuthorDetailOut)
def get_author(email: str, file_limit: int = 10, module_limit: int = 8):
    rows = run_query(queries.AUTHOR_DETAIL, {"email": email})
    if not rows or rows[0].get("commit_count") is None:
        raise HTTPException(status_code=404, detail=f"No author found with email '{email}'.")
    row = rows[0]
    top_files = run_query(queries.AUTHOR_TOP_FILES, {"email": email, "limit": file_limit})
    top_modules = run_query(queries.AUTHOR_TOP_MODULES, {"email": email, "limit": module_limit})

    return AuthorDetailOut(
        email=row["email"],
        name=row["name"],
        commit_count=row["commit_count"],
        file_count=row["file_count"],
        first_commit_at=row["first_ts"],
        last_commit_at=row["last_ts"],
        top_files=[
            AuthorFileOut(path=f["path"], module=f["module"] or "", commit_count=f["commit_count"])
            for f in top_files
        ],
        top_modules=[{"name": m["name"], "touches": m["touches"]} for m in top_modules],
    )
