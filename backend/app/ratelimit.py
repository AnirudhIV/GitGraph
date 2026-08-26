"""Lightweight in-memory rate limiting.

Hand-rolled rather than a library (e.g. slowapi): this app already assumes
a single process for its job tracker (see app.ingest's module-level job
dict), so an in-process counter costs nothing extra and needs no new
dependency -- the same reasoning seed/mine_git.py gives for shelling out to
`git` instead of adding a library for it. If this ever runs behind multiple
worker processes, per-worker counters stop being accurate and a shared
backend (e.g. Redis) would be needed instead.
"""
import threading
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request

_lock = threading.Lock()
_hits: dict[str, deque[float]] = defaultdict(deque)


def client_ip(request: Request) -> str:
    """The client's IP for rate-limit bucketing.

    Reads request.client.host directly. If this is ever deployed behind a
    reverse proxy (nginx, Render, Fly.io, ...), every client will appear to
    share the proxy's IP unless this is changed to trust a specific
    X-Forwarded-For header -- kept as a single function so that's a one-line
    fix in one place, not a hunt through every call site.
    """
    return request.client.host if request.client else "unknown"


def enforce(key: str, max_hits: int, window_seconds: float) -> None:
    """Raise 429 if `key` has already hit this limit within the trailing window.

    A plain fixed-key sliding-window counter: each call either records a hit
    (and returns) or raises without recording one, so a rejected request
    never counts against the caller's own quota.
    """
    now = time.time()
    with _lock:
        hits = _hits[key]
        while hits and now - hits[0] > window_seconds:
            hits.popleft()
        if len(hits) >= max_hits:
            retry_after = max(1, int(window_seconds - (now - hits[0])) + 1)
            raise HTTPException(
                status_code=429,
                detail=f"Too many requests. Try again in about {retry_after}s.",
                headers={"Retry-After": str(retry_after)},
            )
        hits.append(now)
