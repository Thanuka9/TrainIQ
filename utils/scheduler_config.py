"""Control which process runs APScheduler background jobs."""
from __future__ import annotations

import os


def _is_production() -> bool:
    return os.getenv('FLASK_ENV', 'development').lower() in ('production', 'prod')


def should_run_scheduler() -> bool:
    """
    Web workers in production should set RUN_SCHEDULER=false.
    A single ops/dedicated worker sets RUN_SCHEDULER=true.
    Development defaults to true for convenience.
    """
    explicit = (os.getenv('RUN_SCHEDULER') or '').strip().lower()
    if explicit in ('1', 'true', 'yes'):
        return True
    if explicit in ('0', 'false', 'no'):
        return False
    return not _is_production()


def scheduler_jobs_for_ops_only() -> bool:
    """When true, only platform ops jobs register (not email/trial digests)."""
    return (os.getenv('OPS_WORKER_MODE') or '').strip().lower() in ('1', 'true', 'yes')
