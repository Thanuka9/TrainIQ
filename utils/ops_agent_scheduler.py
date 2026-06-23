"""Background scheduler for Platform Operations AI agents."""
from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)


def ops_agents_job():
    """Refresh all ops agent health reports (rule-based + optional AI narrative)."""
    from extensions import scheduler

    if os.getenv('OPS_AGENTS_ENABLED', 'true').lower() in ('0', 'false', 'no'):
        return

    app = scheduler.app
    if app.config.get('TESTING'):
        return

    with app.app_context():
        try:
            from utils.ops_agents import run_all_ops_agents
            from utils.ops_probe_schedule import skip_ops_agents_refresh

            defer, reason = skip_ops_agents_refresh()
            if defer:
                app.logger.info('[ops_agents] Deferred refresh — %s', reason)
                return

            results = run_all_ops_agents()
            unhealthy = sum(1 for r in results.values() if r.get('status') != 'healthy')
            app.logger.info(
                '[ops_agents] Background refresh complete — %s/%s domains need attention',
                unhealthy,
                len(results),
            )
        except Exception as exc:
            app.logger.error('[ops_agents] Background job failed: %s', exc, exc_info=True)


def init_ops_agents_scheduler(scheduler):
    hours = max(1, int(os.getenv('OPS_AGENTS_INTERVAL_HOURS', '2')))
    scheduler.add_job(
        id='platform_ops_agents',
        func=ops_agents_job,
        trigger='interval',
        hours=hours,
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        jitter=180,
    )
    logger.info('[ops_agents] Scheduled every %s hour(s)', hours)
