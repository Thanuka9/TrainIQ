"""TrainIQ DB Platform — single entry point for all database operations.

CEO UI, app startup, background jobs, and CLI scripts all call this module.
No manual flask/psql/SQL coding required for day-to-day operations.
"""
from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)


def _schema_guards_frozen() -> bool:
    from utils.startup_schema import schema_guards_frozen

    return schema_guards_frozen()


def bootstrap_database(*, include_mongo: bool = True) -> dict[str, Any]:
    """
    Full idempotent bootstrap: Alembic migrations, schema guards, backfills, Mongo indexes.
    Called automatically on app startup and by the CEO 'Run full maintenance' button.
    """
    from utils.db_maintenance_lock import platform_maintenance_lock

    with platform_maintenance_lock(blocking=True):
        return _bootstrap_database_impl(include_mongo=include_mongo)


def _bootstrap_database_impl(*, include_mongo: bool = True) -> dict[str, Any]:
    from flask_migrate import upgrade as migrate_upgrade

    from utils.db_maintenance import (
        get_migration_status,
        run_data_backfills,
        run_mongo_maintenance,
        run_schema_guards,
    )

    steps: list[dict[str, Any]] = []

    try:
        before = get_migration_status()
        migrate_upgrade()
        after = get_migration_status()
        steps.append({
            'step': 'alembic_migrations',
            'ok': not after.get('pending', True),
            'message': 'Alembic migrations applied.',
            'before': before,
            'after': after,
        })
    except Exception as exc:
        logger.error('[db_platform] migrate failed: %s', exc, exc_info=True)
        steps.append({'step': 'alembic_migrations', 'ok': False, 'message': str(exc)})

    for fn, name in (
        (lambda: run_schema_guards(manual=True, force=not _schema_guards_frozen()), 'schema_guards'),
        (run_data_backfills, 'data_backfills'),
    ):
        try:
            step = fn()
            steps.append(step)
        except Exception as exc:
            steps.append({'step': name, 'ok': False, 'message': str(exc)})

    if include_mongo:
        try:
            steps.append(run_mongo_maintenance())
        except Exception as exc:
            steps.append({'step': 'mongodb_indexes', 'ok': True, 'message': f'Mongo skipped: {exc}', 'skipped': True})

    ok = all(s.get('ok', False) for s in steps if not s.get('skipped'))
    return {'status': 'success' if ok else 'partial', 'steps': steps}


def ensure_database_healthy(*, apply_safe: bool = False) -> dict[str, Any]:
    """Background / scheduled health pass: scan + optional safe optimizations."""
    from utils.platform_ops_orchestrator import run_health_cycle

    return run_health_cycle(source='scheduler', apply_safe=apply_safe, blocking_lock=False)


def run_full_maintenance(
    *,
    actor_user_id: int | None = None,
    restart: bool = False,
    apply_manual: bool = False,
) -> dict[str, Any]:
    """CEO one-click: bootstrap + health scan + indexes (+ optional manual opts + restart)."""
    from utils.db_maintenance import run_full_maintenance as _run

    return _run(
        actor_user_id=actor_user_id,
        restart=restart,
        apply_manual=apply_manual,
    )


def get_ops_status() -> dict[str, Any]:
    """Unified status for CEO dashboard and /health."""
    from utils.db_maintenance import get_migration_status, latest_maintenance_run, load_db_health_page_data
    from utils.db_optimizer_agent import latest_snapshot_summary

    return {
        'migration': get_migration_status(),
        'monitor': latest_snapshot_summary(),
        'last_maintenance': latest_maintenance_run(),
        'page': load_db_health_page_data(),
        'auto_apply': os.getenv('DB_OPTIMIZER_AUTO_APPLY', '').lower() in ('1', 'true', 'yes'),
        'monitor_enabled': os.getenv('DB_MONITOR_ENABLED', 'true').lower() not in ('0', 'false', 'no'),
    }
