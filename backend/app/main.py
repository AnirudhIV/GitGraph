import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app import db, ratelimit
from app.config import get_settings
from app.routers import authors, files, modules, repo, search

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("app")


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_driver()
    connected = db.verify_connectivity()
    if connected:
        logger.info("Connected to CognoDB.")
    else:
        logger.warning("Could not verify CognoDB connectivity at startup; will retry per-request.")
    yield
    db.close_driver()


app = FastAPI(title="GitGraph API", version="1.0.0", lifespan=lifespan)

settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# General per-IP ceiling on read traffic, separate from the tighter,
# ingest-specific limits in app.routers.repo -- mainly to stop scripted
# flooding of /api/hotspots now that its query can take several seconds on
# a repo of any real size (see app.queries.HOTSPOTS_SIMPLE/ROLLUP).
READ_RATE_LIMIT = 120
READ_RATE_WINDOW_SECONDS = 60


@app.middleware("http")
async def read_rate_limit(request: Request, call_next):
    if request.method == "GET" and request.url.path.startswith("/api/") and request.url.path != "/api/health":
        try:
            ratelimit.enforce(
                f"read:{ratelimit.client_ip(request)}",
                max_hits=READ_RATE_LIMIT,
                window_seconds=READ_RATE_WINDOW_SECONDS,
            )
        except HTTPException as exc:
            return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail}, headers=exc.headers)
    return await call_next(request)


@app.exception_handler(db.DatabaseUnavailableError)
async def db_unavailable_handler(request: Request, exc: db.DatabaseUnavailableError):
    logger.error("Database unavailable: %s", exc)
    return JSONResponse(
        status_code=503,
        content={"detail": "The graph database is unreachable right now. Please try again shortly."},
    )


@app.get("/api/health")
def health():
    return {"status": "ok", "database_connected": db.verify_connectivity()}


app.include_router(repo.router, prefix="/api", tags=["repo"])
app.include_router(files.router, prefix="/api", tags=["files"])
app.include_router(authors.router, prefix="/api", tags=["authors"])
app.include_router(modules.router, prefix="/api", tags=["modules"])
app.include_router(search.router, prefix="/api", tags=["search"])
