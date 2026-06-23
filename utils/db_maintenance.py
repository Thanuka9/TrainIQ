"""CEO-triggered full database maintenance: migrations, schema, indexes, Mongo, scan, restart."""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from typing import Any

from sqlalchemy import text

logger = logging.getLogger(__name__)


def _step(name: str, ok: bool, message: str, **detail) -> dict[str, Any]:
    return {'step': name, 'ok': ok, 'message': message, 'detail': detail or None}


def get_migration_status() -> dict[str, Any]:
    """Compare alembic_version in DB to repository head revision(s)."""
    from flask import current_app
    from extensions import db

    result: dict[str, Any] = {
        'current': None,
        'heads': [],
        'pending': False,
        'pending_revisions': [],
    }
    try:
        from alembic.script import ScriptDirectory

        migrate_ext = current_app.extensions.get('migrate')
        if not migrate_ext:
            result['error'] = 'Flask-Migrate not initialized'
            return result

        config = migrate_ext.migrate.get_config()
        script = ScriptDirectory.from_config(config)
        heads = script.get_heads()
        result['heads'] = heads

        conn = db.engine.connect()
        try:
            row = conn.execute(text('SELECT version_num FROM alembic_version')).fetchone()
            result['current'] = row[0] if row else None
        except Exception:
            result['current'] = None
        finally:
            conn.close()

        if not result['current']:
            result['pending'] = bool(heads)
            result['pending_revisions'] = heads
        else:
            result['pending'] = result['current'] not in heads
            if result['pending']:
                result['pending_revisions'] = [h for h in heads if h != result['current']]
    except Exception as exc:
        logger.warning('Migration status check failed: %s', exc)
        result['error'] = str(exc)

    return result


def run_alembic_upgrade() -> dict[str, Any]:
    from flask_migrate import upgrade as migrate_upgrade
    from utils.db_maintenance_lock import platform_maintenance_lock

    with platform_maintenance_lock(blocking=True):
        before = get_migration_status()
        migrate_upgrade()
        after = get_migration_status()
    ok = not after.get('pending', True)
    return _step(
        'alembic_migrations',
        ok,
        'Alembic migrations applied.' if ok else 'Migrations ran but database may still be behind head.',
        before=before,
        after=after,
    )


def run_schema_guards(*, manual: bool = False, force: bool = False) -> dict[str, Any]:
    if os.getenv('SCHEMA_GUARDS_ENABLED', 'true').lower() in ('0', 'false', 'no'):
        return _step('schema_guards', True, 'Schema guards disabled (SCHEMA_GUARDS_ENABLED=false)', skipped=True)

    from utils.maintenance_window import scheduled_maintenance_allowed
    from utils.startup_schema import schema_guards_frozen

    if schema_guards_frozen() and not force:
        return _step(
            'schema_guards',
            True,
            'Frozen in production — apply schema changes via Alembic migrations only',
            skipped=True,
            frozen=True,
        )

    if not manual and not force:
        allowed, reason = scheduled_maintenance_allowed(manual=False, source='schema_guards')
        if not allowed:
            return _step('schema_guards', True, f'Deferred during {reason}', skipped=True)

    from utils.startup_schema import apply_startup_schema_guards

    result = apply_startup_schema_guards(force=force or manual)
    ok = not result.get('errors')
    msg = (
        f"Schema guards applied ({result.get('applied', 0)} statements, "
        f"{result.get('skipped', 0)} skipped)."
    )
    if result.get('errors'):
        msg += f" {len(result['errors'])} error(s)."
    return _step('schema_guards', ok, msg, **result)


def run_data_backfills() -> dict[str, Any]:
    from utils.billing_plans import backfill_missing_trial_dates
    from utils.platform_ceo import ensure_platform_ceo

    errors: list[str] = []
    try:
        from app import run_catalog_backfill, run_tenant_backfill

        run_tenant_backfill()
        run_catalog_backfill()
        backfill_missing_trial_dates()
        ensure_platform_ceo()
    except Exception as exc:
        errors.append(str(exc))
        logger.error('[maintenance] backfill failed: %s', exc, exc_info=True)

    ok = not errors
    return _step(
        'data_backfills',
        ok,
        'Tenant, catalog, trial, and CEO backfills completed.' if ok else errors[0],
        errors=errors,
    )


def run_mongo_maintenance() -> dict[str, Any]:
    from utils.mongo_platform import bootstrap_mongo

    result = bootstrap_mongo(provision_tenants=True)
    steps = result.get('steps') or []
    ok = result.get('status') == 'success' or all(s.get('ok') for s in steps if not s.get('skipped'))
    msg_parts = [s.get('message', '') for s in steps]
    return _step(
        'mongodb_indexes',
        ok if result.get('status') != 'skipped' else True,
        ' '.join(msg_parts) or 'MongoDB maintenance complete.',
        skipped=result.get('status') == 'skipped',
        steps=steps,
    )


def run_postgres_analyze() -> dict[str, Any]:
    """Refresh PostgreSQL planner statistics on hot tables."""
    from sqlalchemy import inspect

    from extensions import db
    from utils.db_catalog import ANALYZE_TABLES

    conn = db.engine.connect()
    analyzed = skipped = errors = 0
    error_msgs: list[str] = []
    try:
        if conn.dialect.name != 'postgresql':
            return _step(
                'postgres_analyze',
                True,
                'Skipped — not PostgreSQL.',
                skipped=len(ANALYZE_TABLES),
            )
        tables = set(inspect(conn).get_table_names())
        for table in ANALYZE_TABLES:
            if table not in tables:
                skipped += 1
                continue
            try:
                conn.execute(text(f'ANALYZE {table}'))
                conn.commit()
                analyzed += 1
            except Exception as exc:
                errors += 1
                error_msgs.append(f'{table}: {exc}')
    finally:
        conn.close()

    ok = errors == 0
    msg = f'ANALYZE on {analyzed} table(s), {skipped} skipped.'
    if errors:
        msg += f' {errors} error(s).'
    return _step(
        'postgres_analyze',
        ok,
        msg,
        analyzed=analyzed,
        skipped=skipped,
        errors=errors,
        error_msgs=error_msgs[:5],
    )


def run_health_scan_and_indexes(*, apply_manual: bool = False) -> dict[str, Any]:
    from utils.db_optimizer_agent import apply_all_manual_recommendations
    from utils.platform_ops_orchestrator import run_health_cycle

    result = run_health_cycle(
        source='ceo_maintenance',
        apply_safe=True,
        blocking_lock=False,
    )
    monitor = result.get('monitor') or {}
    apply_result = result.get('indexes') or {'applied': 0, 'failed': 0, 'skipped': 0}
    manual_result = {'applied': 0, 'failed': 0}
    if apply_manual:
        manual_result = apply_all_manual_recommendations(monitor.get('snapshot_id'))
    ok = apply_result.get('failed', 0) == 0 and manual_result.get('failed', 0) == 0
    return _step(
        'health_scan_indexes',
        ok,
        (
            f"Health scan complete (status {monitor.get('status')}). "
            f"Safe: {apply_result.get('applied', 0)} applied, {apply_result.get('failed', 0)} failed. "
            f"Manual: {manual_result.get('applied', 0)} applied, {manual_result.get('failed', 0)} failed."
        ),
        monitor=monitor,
        safe_indexes=apply_result,
        manual_indexes=manual_result,
    )


def run_full_maintenance(
    *,
    actor_user_id: int | None = None,
    restart: bool = False,
    apply_manual: bool = False,
) -> dict[str, Any]:
    """
    One-click maintenance pipeline for the CEO console.
    Returns run record dict with steps and overall status.
    """
    from extensions import db
    from models import DbMaintenanceRun
    from utils.db_maintenance_lock import platform_maintenance_lock

    with platform_maintenance_lock(blocking=True):
        return _run_full_maintenance_impl(
            actor_user_id=actor_user_id,
            restart=restart,
            apply_manual=apply_manual,
        )


def _run_full_maintenance_impl(
    *,
    actor_user_id: int | None = None,
    restart: bool = False,
    apply_manual: bool = False,
) -> dict[str, Any]:
    from extensions import db
    from models import DbMaintenanceRun

    steps: list[dict[str, Any]] = []
    overall_ok = True

    # Migrations first — monitor/maintenance tables may not exist yet.
    try:
        migration_step = run_alembic_upgrade()
    except Exception as exc:
        migration_step = _step('alembic_migrations', False, str(exc))
        logger.error('[maintenance] alembic failed: %s', exc, exc_info=True)
    steps.append(migration_step)
    if not migration_step.get('ok'):
        overall_ok = False

    run = None
    try:
        run = DbMaintenanceRun(
            actor_user_id=actor_user_id,
            status='running',
            restart_requested=restart,
            steps_json=json.dumps(steps),
        )
        db.session.add(run)
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        logger.warning('[maintenance] could not persist run record: %s', exc)

    pipeline = (
        lambda: run_schema_guards(manual=True, force=True),
        run_data_backfills,
        run_mongo_maintenance,
        run_postgres_analyze,
        lambda: run_health_scan_and_indexes(apply_manual=apply_manual),
    )

    for fn in pipeline:
        try:
            step = fn()
        except Exception as exc:
            step = _step(fn.__name__, False, str(exc))
            logger.error('[maintenance] step %s failed: %s', fn.__name__, exc, exc_info=True)
        steps.append(step)
        if not step.get('ok'):
            overall_ok = False

    restart_ok = False
    restart_message = 'Restart not requested.'
    if restart:
        from utils.app_restart import schedule_app_restart

        restart_ok, restart_message = schedule_app_restart(delay_seconds=3.0)
        steps.append(_step('app_restart', restart_ok, restart_message))
        if not restart_ok:
            overall_ok = False

    run_status = 'success' if overall_ok else 'partial'
    if not any(s.get('ok') for s in steps):
        run_status = 'failed'
    run_restart_status = (
        'scheduled' if restart and restart_ok else
        'failed' if restart and not restart_ok else
        'skipped'
    )
    run_id = None

    if run is not None:
        run.completed_at = datetime.utcnow()
        run.status = run_status
        run.restart_status = run_restart_status
        run.steps_json = json.dumps(steps)
        run.error_message = None if overall_ok else '; '.join(
            s['message'] for s in steps if not s.get('ok')
        )[:1000]
        db.session.commit()
        run_id = run.id

    try:
        from audit import log_event
        from models import User

        actor = db.session.get(User, actor_user_id) if actor_user_id else None
        log_event(
            'PLATFORM_DB_MAINTENANCE',
            user=actor,
            status=run_status,
            restart=restart,
            steps=len(steps),
        )
    except Exception as exc:
        logger.warning('[maintenance] audit log skipped: %s', exc)

    try:
        from utils.platform_ops import invalidate_ops_read_caches
        invalidate_ops_read_caches()
    except Exception:
        pass

    return {
        'run_id': run_id,
        'status': run_status,
        'restart_status': run_restart_status,
        'steps': steps,
    }


def latest_maintenance_run() -> dict[str, Any] | None:
    from models import DbMaintenanceRun

    try:
        run = DbMaintenanceRun.query.order_by(DbMaintenanceRun.started_at.desc()).first()
    except Exception as exc:
        logger.debug('latest_maintenance_run skipped: %s', exc)
        return None
    if not run:
        return None
    steps = []
    if run.steps_json:
        try:
            steps = json.loads(run.steps_json)
        except json.JSONDecodeError:
            steps = []
    return {
        'id': run.id,
        'status': run.status,
        'started_at': run.started_at.isoformat() if run.started_at else None,
        'completed_at': run.completed_at.isoformat() if run.completed_at else None,
        'restart_requested': run.restart_requested,
        'restart_status': run.restart_status,
        'steps': steps,
        'error_message': run.error_message,
    }


def load_db_health_page_data(*, cache_seconds: float = 0) -> dict[str, Any]:
    """Load DB Health dashboard data; safe when monitor tables are not migrated yet."""
    from utils.db_read_cache import get_cached

    if cache_seconds > 0:
        return get_cached(
            'db_health_page_data',
            cache_seconds,
            lambda: _load_db_health_page_data_uncached(),
        )
    return _load_db_health_page_data_uncached()


def _load_db_health_page_data_uncached() -> dict[str, Any]:
    import json

    from models import DbOptimizationRecommendation, DbPerformanceSnapshot
    from utils.tenant_db import run_db_read

    empty: dict[str, Any] = {
        'snapshot': None,
        'summary': {},
        'recommendations': [],
        'postgres_stats': {},
        'mongo_stats': {},
        'history': [],
        'tables_ready': False,
    }

    def _load():
        snapshot = (
            DbPerformanceSnapshot.query.order_by(DbPerformanceSnapshot.collected_at.desc())
            .first()
        )
        history = (
            DbPerformanceSnapshot.query.order_by(DbPerformanceSnapshot.collected_at.desc())
            .limit(12)
            .all()
        )
        return snapshot, history

    try:
        snapshot, history = run_db_read(_load, label='db_health_page')
    except Exception as exc:
        logger.debug('DB health page: monitor tables unavailable: %s', exc)
        return empty

    data = {**empty, 'snapshot': snapshot, 'history': history, 'tables_ready': True}
    if not snapshot:
        return data

    def _load_recs():
        return (
            DbOptimizationRecommendation.query.filter_by(snapshot_id=snapshot.id)
            .order_by(
                DbOptimizationRecommendation.status.asc(),
                DbOptimizationRecommendation.tier.asc(),
                DbOptimizationRecommendation.id.asc(),
            )
            .all()
        )

    try:
        data['recommendations'] = run_db_read(_load_recs, label='db_health_recs')
    except Exception as exc:
        logger.debug('DB health page: recommendations unavailable: %s', exc)
        data['recommendations'] = []
    if snapshot.summary_json:
        try:
            data['summary'] = json.loads(snapshot.summary_json)
        except json.JSONDecodeError:
            data['summary'] = {}
    if snapshot.postgres_stats_json:
        try:
            data['postgres_stats'] = json.loads(snapshot.postgres_stats_json)
        except json.JSONDecodeError:
            data['postgres_stats'] = {}
    if snapshot.mongo_stats_json:
        try:
            data['mongo_stats'] = json.loads(snapshot.mongo_stats_json)
        except json.JSONDecodeError:
            data['mongo_stats'] = {}
    return data
