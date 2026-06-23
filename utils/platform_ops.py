"""TrainIQ Platform Operations — Postgres, MongoDB, AI, integrations in one module."""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def get_platform_ops_status(*, cache_seconds: float = 0) -> dict[str, Any]:
    """Unified ops dashboard payload (all services)."""
    return get_platform_ops_status_for_tab('overview', cache_seconds=cache_seconds)


def get_platform_ops_status_for_tab(tab: str, *, cache_seconds: float = 0) -> dict[str, Any]:
    """Load ops payload scoped to the active Operations Console tab."""
    from utils.db_read_cache import get_cached

    tab = (tab or 'overview').lower()
    if tab == 'overview':
        if cache_seconds > 0:
            return get_cached(
                'platform_ops_status',
                cache_seconds,
                lambda: _get_platform_ops_status_uncached(),
            )
        return _get_platform_ops_status_uncached()

    cache_key = f'platform_ops_tab:{tab}'
    if cache_seconds > 0:
        return get_cached(cache_key, cache_seconds, lambda: _build_tab_ops_payload(tab))
    return _build_tab_ops_payload(tab)


def _aggregate_ops_status(*parts: dict[str, Any]) -> str:
    critical = any((p or {}).get('status') == 'critical' for p in parts if isinstance(p, dict))
    warning = any(
        (p or {}).get('status') in ('warning', 'degraded', 'partial')
        for p in parts if isinstance(p, dict)
    )
    return 'critical' if critical else 'warning' if warning else 'healthy'


def _header_summary_from_snapshot() -> dict[str, Any]:
    """Lightweight status for hero pills without live service probes."""
    from utils.db_maintenance import get_migration_status
    from utils.db_optimizer_agent import latest_snapshot_summary
    from utils.snapshot_read import load_latest_snapshot_payload

    payload = load_latest_snapshot_payload()
    mongo = dict(payload.get('mongo_stats') or {})
    if mongo:
        mongo.setdefault('status', payload.get('status', 'healthy'))
        mongo['from_snapshot'] = True
    else:
        mongo = {'available': False, 'status': 'unknown', 'from_snapshot': True}

    ai_stub = (payload.get('summary') or {}).get('ai') if isinstance(payload.get('summary'), dict) else {}
    if not isinstance(ai_stub, dict):
        ai_stub = {'status': 'unknown', 'from_snapshot': True}
    else:
        ai_stub = dict(ai_stub)
        ai_stub['from_snapshot'] = True

    integrations_stub = {'status': 'unknown', 'checks': [], 'from_snapshot': True}
    monitor = latest_snapshot_summary() or {}
    migration = get_migration_status()
    status = _aggregate_ops_status(monitor, mongo, ai_stub, integrations_stub)
    return {
        'status': status,
        'migration': migration,
        'monitor': monitor,
        'mongo': mongo,
        'ai': ai_stub,
        'integrations': integrations_stub,
    }


def _build_tab_ops_payload(tab: str) -> dict[str, Any]:
    summary = _header_summary_from_snapshot()
    postgres = {
        'migration': summary['migration'],
        'monitor': summary['monitor'],
        'last_maintenance': {},
        'page': {},
    }
    mongo = summary['mongo']
    ai = summary['ai']
    integrations = summary['integrations']

    if tab == 'postgres':
        from utils.db_maintenance import latest_maintenance_run, load_db_health_page_data

        postgres['last_maintenance'] = latest_maintenance_run()
        postgres['page'] = load_db_health_page_data()
    elif tab == 'mongo':
        try:
            from utils.mongo_platform import collect_mongo_ops_status

            mongo = collect_mongo_ops_status()
        except Exception as exc:
            mongo = {'available': False, 'reason': str(exc), 'status': 'unavailable'}
    elif tab == 'ai':
        try:
            from utils.ai_platform import get_ai_ops_status

            ai = get_ai_ops_status()
        except Exception as exc:
            ai = {'status': 'unavailable', 'message': str(exc)}
    elif tab == 'integrations':
        try:
            from utils.integrations_platform import get_integrations_status

            integrations = get_integrations_status()
        except Exception as exc:
            integrations = {'status': 'unavailable', 'message': str(exc)}

    status = _aggregate_ops_status(
        postgres.get('monitor') or {},
        mongo,
        ai,
        integrations,
    )
    return {
        'status': status,
        'postgres': postgres,
        'mongo': mongo,
        'ai': ai,
        'integrations': integrations,
    }


def _get_platform_ops_status_uncached() -> dict[str, Any]:
    """Unified ops dashboard payload (uncached)."""
    from utils.ai_platform import get_ai_ops_status
    from utils.db_maintenance import get_migration_status, latest_maintenance_run, load_db_health_page_data
    from utils.db_optimizer_agent import latest_snapshot_summary
    from utils.integrations_platform import get_integrations_status
    from utils.snapshot_read import load_latest_snapshot_payload

    payload = load_latest_snapshot_payload()
    mongo = dict(payload.get('mongo_stats') or {})
    if mongo:
        mongo.setdefault('status', payload.get('status', 'healthy'))
        mongo['from_snapshot'] = True
    else:
        try:
            from utils.mongo_platform import collect_mongo_ops_status

            mongo = collect_mongo_ops_status()
        except Exception as exc:
            mongo = {'available': False, 'reason': str(exc), 'status': 'unavailable'}

    postgres = {
        'migration': get_migration_status(),
        'monitor': latest_snapshot_summary(),
        'last_maintenance': latest_maintenance_run(),
        'page': load_db_health_page_data(),
    }

    try:
        ai = get_ai_ops_status()
    except Exception as exc:
        ai = {'status': 'unavailable', 'message': str(exc)}

    integrations = get_integrations_status()

    statuses = [
        postgres.get('monitor', {}) or {},
        mongo,
        ai,
        integrations,
    ]
    critical = any(s.get('status') == 'critical' for s in statuses if isinstance(s, dict))
    warning = any(s.get('status') in ('warning', 'degraded', 'partial') for s in statuses if isinstance(s, dict))

    return {
        'status': 'critical' if critical else 'warning' if warning else 'healthy',
        'postgres': postgres,
        'mongo': mongo,
        'ai': ai,
        'integrations': integrations,
    }


def invalidate_ops_read_caches() -> None:
    """Clear short-lived ops dashboard caches after maintenance or scans."""
    from utils.db_read_cache import invalidate
    from utils.ops_cache import invalidate_json_cached

    invalidate('db_health_page_data')
    invalidate('platform_ops_status')
    for tab in ('postgres', 'mongo', 'ai', 'integrations'):
        invalidate(f'platform_ops_tab:{tab}')
    invalidate_json_cached('metrics_api')


def run_full_platform_ops(
    *,
    actor_user_id: int | None = None,
    restart: bool = False,
    apply_manual: bool = False,
    clear_ai_cache_all: bool = False,
) -> dict[str, Any]:
    """CEO one-click: Postgres maintenance + Mongo bootstrap + AI cache + integration check."""
    from utils.ai_platform import bootstrap_ai, clear_ai_cache
    from utils.db_maintenance import run_full_maintenance

    pg_result = run_full_maintenance(
        actor_user_id=actor_user_id,
        restart=restart,
        apply_manual=apply_manual,
    )

    mongo_steps: list[dict[str, Any]] = []
    try:
        from utils.mongo_platform import bootstrap_mongo

        mongo_result = bootstrap_mongo(provision_tenants=True)
        mongo_steps = mongo_result.get('steps', [])
    except Exception as exc:
        mongo_steps = [{'step': 'mongo_bootstrap', 'ok': False, 'message': str(exc)}]

    ai_steps: list[dict[str, Any]] = []
    try:
        if clear_ai_cache_all:
            cr = clear_ai_cache(expired_only=False)
            ai_steps.append({
                'step': 'ai_cache_clear_all',
                'ok': cr.get('ok', False),
                'message': f"Removed {cr.get('removed', 0)} cache file(s).",
            })
        ai_result = bootstrap_ai()
        ai_steps.extend(ai_result.get('steps', []))
    except Exception as exc:
        ai_steps.append({'step': 'ai_bootstrap', 'ok': False, 'message': str(exc)})

    all_steps = list(pg_result.get('steps', [])) + mongo_steps + ai_steps
    mongo_ok = all(s.get('ok', False) for s in mongo_steps) if mongo_steps else True
    ai_ok = all(s.get('ok', False) for s in ai_steps) if ai_steps else True
    overall = pg_result.get('status', 'partial')
    if overall == 'success' and mongo_ok and ai_ok:
        final = 'success'
    elif any(s.get('ok') for s in all_steps):
        final = 'partial'
    else:
        final = 'failed'

    try:
        from audit import log_event
        from extensions import db
        from models import User

        actor = db.session.get(User, actor_user_id) if actor_user_id else None
        log_event(
            'PLATFORM_FULL_OPS',
            user=actor,
            status=final,
            restart=restart,
            steps=len(all_steps),
        )
    except Exception as exc:
        logger.warning('[platform_ops] audit skipped: %s', exc)

    invalidate_ops_read_caches()

    return {
        'status': final,
        'postgres': pg_result,
        'mongo_steps': mongo_steps,
        'ai_steps': ai_steps,
        'steps': all_steps,
        'ops': get_platform_ops_status(),
    }
