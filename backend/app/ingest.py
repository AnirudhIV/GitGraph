"""Background repo-ingest jobs triggered from the API.

Ingestion (clone + mine + load) can take from seconds to minutes depending
on repo size, so it runs on a background thread and reports progress
through an in-memory job dict that the frontend polls. A single-process,
in-memory store is fine here: this app has one CognoDB graph at a time, and
a wipe-and-reload ingest can't safely run concurrently with another anyway.
"""
import logging
import threading
import time
import uuid

from seed.load import IngestError, run_ingest

logger = logging.getLogger("app.ingest")

_jobs: dict[str, dict] = {}
_lock = threading.Lock()
_active_job_id: str | None = None


def active_job() -> dict | None:
    with _lock:
        if _active_job_id is None:
            return None
        job = _jobs.get(_active_job_id)
        return dict(job) if job and job["status"] == "running" else None


def get_job(job_id: str) -> dict | None:
    job = _jobs.get(job_id)
    return dict(job) if job else None


def start_job(repo_url: str, max_commits: int = 5000, module_depth: int = 1) -> str:
    global _active_job_id
    with _lock:
        if _active_job_id is not None and _jobs.get(_active_job_id, {}).get("status") == "running":
            raise RuntimeError("An ingest is already running.")
        job_id = uuid.uuid4().hex
        _jobs[job_id] = {
            "job_id": job_id,
            "status": "running",
            "message": "Starting…",
            "repo_url": repo_url,
            "error": None,
            "stats": None,
            "elapsed_seconds": None,
        }
        _active_job_id = job_id

    thread = threading.Thread(target=_run, args=(job_id, repo_url, max_commits, module_depth), daemon=True)
    thread.start()
    return job_id


def _run(job_id: str, repo_url: str, max_commits: int, module_depth: int) -> None:
    def progress(message: str) -> None:
        with _lock:
            _jobs[job_id]["message"] = message

    start = time.time()
    try:
        stats = run_ingest(
            repo_url=repo_url,
            max_commits=max_commits,
            module_depth=module_depth,
            clear=True,
            progress=progress,
        )
        elapsed = round(time.time() - start, 1)
        with _lock:
            _jobs[job_id]["status"] = "done"
            _jobs[job_id]["message"] = f"Done in {elapsed}s"
            _jobs[job_id]["stats"] = stats
            _jobs[job_id]["elapsed_seconds"] = elapsed
    except IngestError as exc:
        with _lock:
            _jobs[job_id]["status"] = "error"
            _jobs[job_id]["error"] = str(exc)
            _jobs[job_id]["elapsed_seconds"] = round(time.time() - start, 1)
    except Exception as exc:  # noqa: BLE001 - surface any failure to the poller instead of dying silently
        logger.exception("Ingest job %s failed", job_id)
        with _lock:
            _jobs[job_id]["status"] = "error"
            _jobs[job_id]["error"] = f"Ingest failed: {exc}"
            _jobs[job_id]["elapsed_seconds"] = round(time.time() - start, 1)
