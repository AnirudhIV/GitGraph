from fastapi import APIRouter, Query

from app import queries
from app.db import run_query
from app.schemas import AuthorSummaryOut, FileSummaryOut, RecentCommitOut, SearchResultOut

router = APIRouter()


@router.get("/search", response_model=SearchResultOut)
def search(q: str = Query(..., min_length=1), limit: int = Query(8, ge=1, le=50)):
    files = run_query(queries.SEARCH_FILES, {"q": q, "limit": limit})
    authors = run_query(queries.SEARCH_AUTHORS, {"q": q, "limit": limit})
    commits = run_query(queries.SEARCH_COMMITS, {"q": q, "limit": limit})

    return SearchResultOut(
        files=[
            FileSummaryOut(
                path=f["path"],
                extension=f["extension"] or "",
                module=f["module"] or "",
                commit_count=f["commit_count"],
                is_deleted=f["is_deleted"],
            )
            for f in files
        ],
        authors=[
            AuthorSummaryOut(
                email=a["email"],
                name=a["name"],
                commit_count=a["commit_count"],
                file_count=a["file_count"],
                first_commit_at=a["first_ts"],
                last_commit_at=a["last_ts"],
            )
            for a in authors
        ],
        commits=[
            RecentCommitOut(
                hash=c["hash"],
                message=c["message"],
                author_name=c["author_name"],
                timestamp=c["timestamp"],
                additions=c["additions"] or 0,
                deletions=c["deletions"] or 0,
            )
            for c in commits
        ],
    )
