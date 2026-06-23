"""APScheduler integration for database performance monitoring."""
from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)


def db_monitor_job():
    """Background job: collect DB metrics, analyze, optionally auto-apply safe indexes."""
    from extensions import scheduler

    if os.getenv('DB_MONITOR_ENABLED', 'true').lower() in ('0', 'false', 'no'):
        return

    app = scheduler.app
    if app.config.get('TESTING'):
        return

    with app.app_context():
        try:
            from utils.platform_ops_orchestrator import run_health_cycle
            from utils.scheduler_config import scheduler_jobs_for_ops_only
            from utils.snapshot_retention import run_snapshot_retention

            # Weekly-ish retention when job fires (cheap no-op if nothing old)
            if os.getenv('DB_SNAPSHOT_RETENTION_ENABLED', 'true').lower() not in ('0', 'false', 'no'):
                run_snapshot_retention()

            auto_apply = os.getenv('DB_OPTIMIZER_AUTO_APPLY', '').lower() in ('1', 'true', 'yes')
            source = 'ops_worker' if scheduler_jobs_for_ops_only() else 'scheduler'
            result = run_health_cycle(source=source, apply_safe=auto_apply, blocking_lock=False)
            if result.get('skipped'):
                app.logger.info('[db_monitor] Skipped — %s', result.get('reason'))
            else:
                app.logger.info(
                    '[db_monitor] Cycle complete — status=%s source=%s',
                    result.get('status'),
                    result.get('source'),
                )
        except Exception as exc:
            app.logger.error('[db_monitor] Cycle failed: %s', exc, exc_info=True)


def init_db_monitor(scheduler):
    """Register the DB monitor job on the shared APScheduler instance."""
    hours = max(1, int(os.getenv('DB_MONITOR_INTERVAL_HOURS', '6')))
    scheduler.add_job(
        id='db_performance_monitor',
        func=db_monitor_job,
        trigger='interval',
        hours=hours,
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        jitter=120,
    )
    logger.info('[db_monitor] Scheduled every %s hour(s)', hours)
