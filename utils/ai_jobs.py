"""In-process background jobs for long-running AI tasks."""
import threading
import time
import uuid
from contextlib import nullcontext
from typing import Any, Callable

_lock = threading.Lock()
_jobs: dict[str, dict] = {}

JOB_TTL = 3600


def _cleanup():
    now = time.time()
    with _lock:
        expired = [k for k, v in _jobs.items() if now - v.get("created", 0) > JOB_TTL]
        for k in expired:
            del _jobs[k]


def create_job(user_id, task_type, tenant_id=None):
    _cleanup()
    job_id = str(uuid.uuid4())
    with _lock:
        _jobs[job_id] = {
            "id": job_id,
            "user_id": user_id,
            "tenant_id": tenant_id,
            "task": task_type,
            "status": "pending",
            "result": None,
            "error": None,
            "created": time.time(),
        }
    return job_id


def get_job(job_id, user_id=None, tenant_id=None):
    with _lock:
        job = _jobs.get(job_id)
        if not job:
            return None
        if user_id is not None and job.get("user_id") != user_id:
            return None
        if tenant_id is not None and job.get("tenant_id") not in (None, tenant_id):
            return None
        return dict(job)


def run_job(job_id, fn: Callable[[], Any], app=None):
    def _worker():
        ctx = app.app_context() if app else nullcontext()
        with ctx:
            with _lock:
                if job_id in _jobs:
                    _jobs[job_id]["status"] = "running"
            try:
                result = fn()
                with _lock:
                    if job_id in _jobs:
                        _jobs[job_id]["status"] = "complete"
                        _jobs[job_id]["result"] = result
            except Exception as e:
                with _lock:
                    if job_id in _jobs:
                        _jobs[job_id]["status"] = "failed"
                        _jobs[job_id]["error"] = str(e)

    threading.Thread(target=_worker, daemon=True).start()
