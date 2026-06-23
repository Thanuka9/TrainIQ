"""AI-assisted operations agents for the Platform Operations Console.

Each domain (postgres, mongo, ai, integrations, system, audit, overview) has a
dedicated agent that collects health metrics, produces rule-based findings, and
optionally enriches them with a local Ollama narrative.
"""
from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any

from utils.ops_constants import (
    AI_CACHE_MAX_MB,
    AI_LATENCY_WARN_MS,
    PG_CACHE_HIT_RATIO_WARN,
    PG_SLOW_QUERY_MS,
)

logger = logging.getLogger(__name__)

VALID_DOMAINS = frozenset({
    'overview', 'postgres', 'mongo', 'ai', 'integrations', 'system', 'audit',
})

AGENT_META: dict[str, dict[str, str]] = {
    'overview': {'name': 'Platform Chief Agent', 'icon': 'gauge', 'role': 'orchestrator'},
    'postgres': {'name': 'PostgreSQL Agent', 'icon': 'database', 'role': 'database engine'},
    'mongo': {'name': 'MongoDB Agent', 'icon': 'leaf', 'role': 'document & file store'},
    'ai': {'name': 'LearnIQ Agent', 'icon': 'brain', 'role': 'local AI engine'},
    'integrations': {'name': 'Integrations Agent', 'icon': 'plug', 'role': 'third-party services'},
    'system': {'name': 'System Agent', 'icon': 'gears', 'role': 'host & scheduler'},
    'audit': {'name': 'Audit Agent', 'icon': 'shield-halved', 'role': 'platform activity'},
}

CACHE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    'instance',
    'ops_agents',
)
CACHE_TTL = max(300, int(os.getenv('OPS_AGENTS_CACHE_TTL', '1800')))
USE_AI_DEFAULT = os.getenv('OPS_AGENTS_USE_AI', 'true').lower() in ('1', 'true', 'yes')


def _cache_path(domain: str) -> str:
    os.makedirs(CACHE_DIR, exist_ok=True)
    return os.path.join(CACHE_DIR, f'{domain}.json')


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat() + 'Z'


def _load_cached(domain: str) -> dict[str, Any] | None:
    path = _cache_path(domain)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        updated = data.get('updated_at', '')
        if updated:
            ts = datetime.fromisoformat(updated.rstrip('Z'))
            age = (datetime.utcnow() - ts).total_seconds()
            data['cache_age_seconds'] = int(age)
            data['stale'] = age > CACHE_TTL
        return data
    except (json.JSONDecodeError, OSError, ValueError):
        return None


def _save_report(report: dict[str, Any]) -> None:
    domain = report.get('domain')
    if not domain:
        return
    path = _cache_path(domain)
    try:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(report, f, indent=2, default=str)
    except OSError as exc:
        logger.warning('[ops_agents] cache write failed for %s: %s', domain, exc)


def load_all_agent_reports() -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for domain in VALID_DOMAINS:
        cached = _load_cached(domain)
        if cached:
            out[domain] = cached
    return out


def get_agent_report(domain: str, *, refresh_if_stale: bool = False) -> dict[str, Any]:
    if domain not in VALID_DOMAINS:
        raise ValueError(f'Unknown ops agent domain: {domain}')
    cached = _load_cached(domain)
    if cached and not cached.get('stale') and not refresh_if_stale:
        return cached
    if cached and not refresh_if_stale:
        return cached
    return run_ops_agent(domain, force=True, use_ai=USE_AI_DEFAULT)


def _severity_rank(status: str) -> int:
    return {'healthy': 0, 'warning': 1, 'degraded': 2, 'critical': 3}.get(status, 1)


def _worst_status(*statuses: str) -> str:
    if not statuses:
        return 'healthy'
    return max(statuses, key=_severity_rank)


def _health_score(status: str, issue_count: int = 0) -> int:
    base = {'healthy': 95, 'warning': 72, 'degraded': 55, 'critical': 30}.get(status, 70)
    return max(10, base - min(issue_count * 5, 40))


def _agents_use_live_probe() -> bool:
    return os.getenv('OPS_AGENTS_LIVE_PROBE', 'false').lower() in ('1', 'true', 'yes')


def _cached_agent_metrics(domain: str) -> dict[str, Any] | None:
    cached = _load_cached(domain)
    if cached and not cached.get('stale') and cached.get('metrics'):
        return cached['metrics']
    return None


def _collect_postgres_context() -> dict[str, Any]:
    from utils.db_maintenance import get_migration_status, latest_maintenance_run
    from utils.snapshot_read import load_latest_snapshot_payload

    payload = load_latest_snapshot_payload()
    cap = (payload.get('postgres_stats') or {}).get('capacity') or {}
    migration = get_migration_status()

    return {
        'from_snapshot': bool(payload.get('snapshot_id')),
        'snapshot_id': payload.get('snapshot_id'),
        'migration_pending': migration.get('pending', False),
        'migration_head': (migration.get('heads') or [''])[0],
        'migration_current': migration.get('current'),
        'tables_ready': payload.get('tables_ready', False),
        'snapshot_status': payload.get('status'),
        'issue_count': payload.get('issue_count', 0),
        'recommendation_count': payload.get('recommendation_count', 0),
        'pending_recommendations': payload.get('pending_recommendations', 0),
        'database_size_mb': cap.get('database_size_mb'),
        'cache_hit_ratio': cap.get('cache_hit_ratio'),
        'connections': cap.get('connections') or {},
        'slow_queries': len(cap.get('slow_queries') or []),
        'last_maintenance': latest_maintenance_run(),
        'last_scan_at': payload.get('collected_at'),
    }


def _analyze_postgres(ctx: dict[str, Any]) -> tuple[str, list, list, str, int]:
    findings: list[dict[str, str]] = []
    actions: list[dict[str, Any]] = [
        {'id': 'scan', 'label': 'Run DB health scan', 'safe': True},
        {'id': 'apply_safe', 'label': 'Apply safe fixes', 'safe': True},
    ]
    status = 'healthy'

    if ctx.get('migration_pending'):
        status = 'warning'
        findings.append({
            'severity': 'warning',
            'title': 'Pending Alembic migrations',
            'detail': 'Schema is behind head revision — run maintenance to apply migrations.',
        })
        actions.append({'id': 'run_maintenance', 'label': 'Run full maintenance', 'safe': False})

    if not ctx.get('tables_ready'):
        status = _worst_status(status, 'warning')
        findings.append({
            'severity': 'warning',
            'title': 'Monitor tables missing',
            'detail': 'DB performance monitor tables are not initialized yet.',
        })

    issue_count = ctx.get('issue_count') or 0
    if issue_count > 0:
        status = _worst_status(status, 'warning' if issue_count < 5 else 'critical')
        findings.append({
            'severity': 'warning' if issue_count < 5 else 'critical',
            'title': f'{issue_count} performance issue(s) detected',
            'detail': 'Review recommendations and apply safe fixes.',
        })

    pending = ctx.get('pending_recommendations') or 0
    if pending > 0:
        findings.append({
            'severity': 'info',
            'title': f'{pending} pending recommendation(s)',
            'detail': 'Safe index and analyze tasks can be applied automatically.',
        })
        if pending > 0:
            actions.append({'id': 'apply_safe', 'label': f'Apply {pending} safe fix(es)', 'safe': True})

    ratio = ctx.get('cache_hit_ratio')
    if ratio is not None and ratio < PG_CACHE_HIT_RATIO_WARN:
        status = _worst_status(status, 'warning')
        findings.append({
            'severity': 'warning',
            'title': 'Low buffer cache hit ratio',
            'detail': f'Cache hit ratio is {ratio:.1%} (target ≥{PG_CACHE_HIT_RATIO_WARN:.0%}). Consider more RAM or query tuning.',
        })

    slow = ctx.get('slow_queries') or 0
    if slow > 0:
        status = _worst_status(status, 'warning')
        findings.append({
            'severity': 'warning',
            'title': f'{slow} slow quer{"y" if slow == 1 else "ies"}',
            'detail': f'Queries exceeding {PG_SLOW_QUERY_MS}ms detected in pg_stat_statements.',
        })

    if not ctx.get('last_scan_at'):
        findings.append({
            'severity': 'info',
            'title': 'No health scan on record',
            'detail': 'Run a scan to establish a performance baseline.',
        })

    summary = (
        'PostgreSQL is healthy and up to date.'
        if status == 'healthy' and not findings
        else f'PostgreSQL status: {status}. {len(findings)} finding(s) need attention.'
    )
    score = _health_score(status, issue_count + (1 if ctx.get('migration_pending') else 0))
    return status, findings, actions, summary, score


def _collect_mongo_context() -> dict[str, Any]:
    from utils.snapshot_read import load_latest_snapshot_payload

    payload = load_latest_snapshot_payload()
    mongo = dict(payload.get('mongo_stats') or {})
    if mongo:
        mongo['from_snapshot'] = True
        mongo.setdefault('status', payload.get('status', 'healthy'))
        return mongo

    if os.getenv('OPS_AGENTS_LIVE_MONGO_PROBE', 'false').lower() in ('1', 'true', 'yes'):
        from utils.mongo_platform import collect_mongo_ops_status

        try:
            return collect_mongo_ops_status()
        except Exception as exc:
            return {'available': False, 'reason': str(exc), 'status': 'unavailable'}

    return {
        'available': False,
        'status': 'unknown',
        'reason': 'No MongoDB snapshot — run a DB health scan first.',
        'from_snapshot': True,
    }


def _analyze_mongo(ctx: dict[str, Any]) -> tuple[str, list, list, str, int]:
    findings: list[dict[str, str]] = []
    actions: list[dict[str, Any]] = [
        {'id': 'bootstrap', 'label': 'Sync MongoDB tenants', 'safe': True},
    ]

    if not ctx.get('available'):
        return (
            'critical',
            [{'severity': 'critical', 'title': 'MongoDB offline', 'detail': ctx.get('reason', 'Connection failed.')}],
            actions,
            'MongoDB is unavailable — course file uploads are degraded.',
            25,
        )

    status = ctx.get('status', 'healthy')
    unprovisioned = ctx.get('unprovisioned_tenants') or 0
    missing_indexes = ctx.get('missing_index_count') or 0

    if unprovisioned > 0:
        status = _worst_status(status, 'warning')
        findings.append({
            'severity': 'warning',
            'title': f'{unprovisioned} tenant DB(s) not provisioned',
            'detail': 'Run Mongo maintenance to create missing tenant databases.',
        })

    if missing_indexes > 0:
        status = _worst_status(status, 'warning')
        findings.append({
            'severity': 'warning',
            'title': f'{missing_indexes} missing index(es)',
            'detail': 'Compound and field indexes improve GridFS and query performance.',
        })
        actions.append({'id': 'sync_indexes', 'label': 'Apply catalog indexes', 'safe': True})

    server = ctx.get('server') or {}
    storage_mb = server.get('total_storage_mb')
    from utils.ops_constants import MONGO_STORAGE_WARN_MB
    if storage_mb and storage_mb > MONGO_STORAGE_WARN_MB:
        status = _worst_status(status, 'warning')
        findings.append({
            'severity': 'warning',
            'title': 'High MongoDB storage usage',
            'detail': f'Total storage {storage_mb} MB exceeds warn threshold ({MONGO_STORAGE_WARN_MB} MB).',
        })

    summary = (
        f'MongoDB healthy — {ctx.get("tenant_db_count", 0)} tenant DB(s) provisioned.'
        if status == 'healthy' and not findings
        else f'MongoDB status: {status}. {len(findings)} finding(s).'
    )
    score = _health_score(status, len(findings))
    return status, findings, actions, summary, score


def _collect_ai_context() -> dict[str, Any]:
    if not _agents_use_live_probe():
        cached = _cached_agent_metrics('ai')
        if cached:
            cached['from_snapshot'] = True
            return cached
        from utils.snapshot_read import load_latest_snapshot_payload

        payload = load_latest_snapshot_payload()
        summary = payload.get('summary') or {}
        ai_stub = summary.get('ai') if isinstance(summary.get('ai'), dict) else {}
        if ai_stub:
            ai_stub['from_snapshot'] = True
            return ai_stub

    from utils.ai_platform import get_ai_ops_status

    try:
        return get_ai_ops_status()
    except Exception as exc:
        return {'status': 'unavailable', 'message': str(exc), 'available': False}


def _analyze_ai(ctx: dict[str, Any]) -> tuple[str, list, list, str, int]:
    findings: list[dict[str, str]] = []
    actions: list[dict[str, Any]] = [
        {'id': 'refresh', 'label': 'Refresh AI status', 'safe': True},
    ]
    status = ctx.get('status', 'healthy')

    if not ctx.get('available'):
        findings.append({
            'severity': 'critical',
            'title': 'Ollama offline',
            'detail': ctx.get('message', 'Start Ollama to enable LearnIQ features.'),
        })
        return 'critical', findings, actions, 'LearnIQ AI engine is offline.', 20

    if not ctx.get('model_ready'):
        status = 'warning'
        findings.append({
            'severity': 'warning',
            'title': 'Model not installed',
            'detail': ctx.get('message', 'Pull the configured Ollama model.'),
        })

    cache = ctx.get('cache') or {}
    if cache.get('over_capacity'):
        status = _worst_status(status, 'warning')
        findings.append({
            'severity': 'warning',
            'title': 'AI cache over capacity',
            'detail': f'Cache is {cache.get("total_mb", 0)} MB (limit {AI_CACHE_MAX_MB} MB).',
        })
        actions.append({'id': 'trim_cache', 'label': 'Trim AI cache', 'safe': True})

    expired = cache.get('expired') or 0
    if expired > 10:
        findings.append({
            'severity': 'info',
            'title': f'{expired} expired cache entries',
            'detail': 'Clear expired entries to reclaim disk space.',
        })
        actions.append({'id': 'clear_expired', 'label': 'Clear expired cache', 'safe': True})

    latency = ctx.get('latency') or {}
    if latency.get('slow'):
        status = _worst_status(status, 'warning')
        findings.append({
            'severity': 'warning',
            'title': 'Slow Ollama response',
            'detail': f'Latency probe took {latency.get("latency_ms")} ms (warn ≥{AI_LATENCY_WARN_MS} ms).',
        })

    jobs = ctx.get('jobs') or {}
    failed = jobs.get('failed') or 0
    if failed > 0:
        status = _worst_status(status, 'warning')
        findings.append({
            'severity': 'warning',
            'title': f'{failed} failed AI job(s)',
            'detail': 'Check recent generation failures in the AI tab.',
        })

    summary = (
        f'LearnIQ ready — model {ctx.get("resolved_model") or "unknown"}.'
        if status == 'healthy' and not findings
        else f'LearnIQ status: {status}. {len(findings)} finding(s).'
    )
    score = _health_score(status, len(findings))
    return status, findings, actions, summary, score


def _collect_integrations_context() -> dict[str, Any]:
    if not _agents_use_live_probe():
        cached = _cached_agent_metrics('integrations')
        if cached:
            cached['from_snapshot'] = True
            return cached
        from utils.platform_ops import get_platform_ops_status

        return get_platform_ops_status(cache_seconds=120).get('integrations', {})

    from utils.integrations_platform import get_integrations_status

    return get_integrations_status()


def _analyze_integrations(ctx: dict[str, Any]) -> tuple[str, list, list, str, int]:
    checks = ctx.get('checks') or []
    findings: list[dict[str, str]] = []
    actions: list[dict[str, Any]] = [
        {'id': 'recheck', 'label': 'Re-check all integrations', 'safe': True},
    ]
    failed = [c for c in checks if not c.get('ok')]
    status = ctx.get('status', 'healthy')

    for check in failed:
        sev = 'warning' if check.get('name') == 'stripe' and not check.get('configured') else 'critical'
        if check.get('mode') == 'memory' and check.get('name') == 'redis':
            sev = 'info'
        findings.append({
            'severity': sev,
            'title': f'{check.get("name", "service").title()} not OK',
            'detail': check.get('detail', 'Check environment configuration.'),
        })
        if sev == 'critical':
            status = _worst_status(status, 'critical')
        elif sev == 'warning':
            status = _worst_status(status, 'warning')

    ok_count = len(checks) - len(failed)
    summary = (
        f'All {len(checks)} integrations connected.'
        if not failed
        else f'{ok_count}/{len(checks)} integrations OK — {len(failed)} need attention.'
    )
    score = _health_score(status, len(failed))
    return status, findings, actions, summary, score


def _collect_system_context() -> dict[str, Any]:
    ctx: dict[str, Any] = {'scheduler_jobs': []}
    try:
        import psutil
        ctx['cpu_percent'] = psutil.cpu_percent(interval=0.1)
        mem = psutil.virtual_memory()
        ctx['mem_percent'] = mem.percent
        ctx['mem_used_mb'] = int(mem.used / (1024 * 1024))
        ctx['mem_total_mb'] = int(mem.total / (1024 * 1024))
    except ImportError:
        ctx['cpu_percent'] = None

    try:
        from extensions import scheduler
        for job in scheduler.get_jobs():
            ctx['scheduler_jobs'].append({
                'id': job.id,
                'next_run': job.next_run_time.isoformat() if job.next_run_time else None,
                'pending': job.pending,
            })
    except Exception as exc:
        ctx['scheduler_error'] = str(exc)

    return ctx


def _analyze_system(ctx: dict[str, Any]) -> tuple[str, list, list, str, int]:
    findings: list[dict[str, str]] = []
    actions: list[dict[str, Any]] = [
        {'id': 'refresh', 'label': 'Refresh system metrics', 'safe': True},
    ]
    status = 'healthy'

    cpu = ctx.get('cpu_percent')
    if cpu is not None and cpu > 85:
        status = 'warning'
        findings.append({
            'severity': 'warning',
            'title': 'High CPU usage',
            'detail': f'CPU at {cpu:.0f}% — consider scaling or investigating background jobs.',
        })

    mem = ctx.get('mem_percent')
    if mem is not None and mem > 90:
        status = _worst_status(status, 'critical')
        findings.append({
            'severity': 'critical',
            'title': 'Critical memory pressure',
            'detail': f'Memory at {mem:.0f}% — risk of OOM kills.',
        })
    elif mem is not None and mem > 80:
        status = _worst_status(status, 'warning')
        findings.append({
            'severity': 'warning',
            'title': 'Elevated memory usage',
            'detail': f'Memory at {mem:.0f}%.',
        })

    jobs = ctx.get('scheduler_jobs') or []
    paused = [j for j in jobs if not j.get('next_run')]
    if paused:
        findings.append({
            'severity': 'info',
            'title': f'{len(paused)} scheduler job(s) paused',
            'detail': 'Some background jobs have no next run time scheduled.',
        })

    summary = (
        'System resources within normal range.'
        if status == 'healthy' and not findings
        else f'System status: {status}. {len(findings)} finding(s).'
    )
    score = _health_score(status, len(findings))
    return status, findings, actions, summary, score


def _collect_audit_context() -> dict[str, Any]:
    try:
        from utils.platform_analytics import get_platform_activity_feed

        events = get_platform_activity_feed(limit=25)
        return {
            'event_count': len(events),
            'recent': events[:10],
            'types': list({e.get('action_type') or e.get('event') for e in events if e}),
        }
    except Exception as exc:
        return {'event_count': 0, 'recent': [], 'error': str(exc)}


def _analyze_audit(ctx: dict[str, Any]) -> tuple[str, list, list, str, int]:
    findings: list[dict[str, str]] = []
    actions: list[dict[str, Any]] = [
        {'id': 'refresh', 'label': 'Refresh activity feed', 'safe': True},
    ]
    status = 'healthy'

    if ctx.get('error'):
        status = 'warning'
        findings.append({
            'severity': 'warning',
            'title': 'Activity feed unavailable',
            'detail': ctx['error'],
        })

    count = ctx.get('event_count') or 0
    critical_events = [
        e for e in (ctx.get('recent') or [])
        if (e.get('status') or '').lower() in ('failed', 'critical', 'error')
    ]
    if critical_events:
        status = 'warning'
        findings.append({
            'severity': 'warning',
            'title': f'{len(critical_events)} recent failure event(s)',
            'detail': 'Review audit log for failed platform operations.',
        })

    summary = f'{count} recent platform events tracked.' if not findings else f'Audit: {len(findings)} alert(s) in recent activity.'
    score = _health_score(status, len(findings))
    return status, findings, actions, summary, score


def _collect_overview_context() -> dict[str, Any]:
    from utils.snapshot_read import load_latest_snapshot_payload

    payload = load_latest_snapshot_payload()
    overall = payload.get('status') or 'healthy'
    if payload.get('issue_count', 0) > 0 and overall == 'healthy':
        overall = 'warning'

    return {
        'overall_status': overall,
        'postgres': _collect_postgres_context(),
        'mongo': _collect_mongo_context(),
        'ai': _collect_ai_context(),
        'integrations': _collect_integrations_context(),
        'system': _collect_system_context(),
    }


def _analyze_overview(ctx: dict[str, Any]) -> tuple[str, list, list, str, int]:
    sub_reports: list[dict[str, Any]] = []
    for domain, collector, analyzer in (
        ('postgres', _collect_postgres_context, _analyze_postgres),
        ('mongo', _collect_mongo_context, _analyze_mongo),
        ('ai', _collect_ai_context, _analyze_ai),
        ('integrations', _collect_integrations_context, _analyze_integrations),
    ):
        sub_ctx = ctx.get(domain) or collector()
        st, findings, _, summary, score = analyzer(sub_ctx)
        sub_reports.append({'domain': domain, 'status': st, 'summary': summary, 'score': score, 'findings': len(findings)})

    statuses = [r['status'] for r in sub_reports]
    status = ctx.get('overall_status') or _worst_status(*statuses)
    findings: list[dict[str, str]] = []
    for r in sub_reports:
        if r['status'] != 'healthy':
            findings.append({
                'severity': r['status'] if r['status'] in ('critical', 'warning') else 'warning',
                'title': f'{AGENT_META[r["domain"]]["name"]}: {r["status"]}',
                'detail': r['summary'],
            })

    actions: list[dict[str, Any]] = [
        {'id': 'refresh_all', 'label': 'Refresh all agents', 'safe': True},
        {'id': 'scan', 'label': 'Run DB health scan', 'safe': True},
        {'id': 'bootstrap', 'label': 'Sync MongoDB', 'safe': True},
    ]

    unhealthy = sum(1 for r in sub_reports if r['status'] != 'healthy')
    summary = (
        'All platform services are healthy.'
        if status == 'healthy'
        else f'Platform status: {status}. {unhealthy} service area(s) need attention.'
    )
    avg_score = int(sum(r['score'] for r in sub_reports) / max(len(sub_reports), 1))
    return status, findings, actions, summary, avg_score


_COLLECTORS = {
    'overview': _collect_overview_context,
    'postgres': _collect_postgres_context,
    'mongo': _collect_mongo_context,
    'ai': _collect_ai_context,
    'integrations': _collect_integrations_context,
    'system': _collect_system_context,
    'audit': _collect_audit_context,
}

_ANALYZERS = {
    'overview': _analyze_overview,
    'postgres': _analyze_postgres,
    'mongo': _analyze_mongo,
    'ai': _analyze_ai,
    'integrations': _analyze_integrations,
    'system': _analyze_system,
    'audit': _analyze_audit,
}


def _generate_narrative(
    domain: str,
    ctx: dict[str, Any],
    findings: list[dict[str, str]],
    summary: str,
) -> tuple[str | None, bool]:
    if not USE_AI_DEFAULT:
        return None, False
    try:
        from utils.local_ai import get_ai_status, query_chat

        ai = get_ai_status()
        if not ai.get('model_ready'):
            return None, False

        meta = AGENT_META[domain]
        compact_ctx = json.dumps(ctx, default=str)[:6000]
        finding_text = '\n'.join(
            f'- [{f["severity"]}] {f["title"]}: {f["detail"]}' for f in findings[:8]
        ) or 'No issues detected.'

        prompt = (
            f'You are the {meta["name"]} for TrainIQ ({meta["role"]}). '
            f'Write a concise CEO briefing (3-5 sentences) on current health, then list '
            f'up to 3 prioritized next steps as short bullets. '
            f'Rule summary: {summary}\nFindings:\n{finding_text}\n\nMetrics:\n{compact_ctx}'
        )
        narrative = query_chat(
            [
                {'role': 'system', 'content': 'You are a concise platform SRE assistant. Plain text only, no markdown.'},
                {'role': 'user', 'content': prompt},
            ],
            temperature=0.2,
            timeout=90,
        )
        return (narrative or None), True
    except Exception as exc:
        logger.debug('[ops_agents] AI narrative skipped for %s: %s', domain, exc)
        return None, False


def run_ops_agent(domain: str, *, force: bool = False, use_ai: bool | None = None) -> dict[str, Any]:
    if domain not in VALID_DOMAINS:
        raise ValueError(f'Unknown domain: {domain}')

    if not force:
        cached = _load_cached(domain)
        if cached and not cached.get('stale'):
            return cached

    meta = AGENT_META[domain]
    ctx = _COLLECTORS[domain]()
    status, findings, actions, summary, score = _ANALYZERS[domain](ctx)

    use_ai_flag = USE_AI_DEFAULT if use_ai is None else use_ai
    narrative, ai_used = (None, False)
    if use_ai_flag:
        narrative, ai_used = _generate_narrative(domain, ctx, findings, summary)

    report: dict[str, Any] = {
        'domain': domain,
        'agent_name': meta['name'],
        'icon': meta['icon'],
        'status': status,
        'health_score': score,
        'summary': summary,
        'narrative': narrative,
        'findings': findings,
        'actions': actions,
        'metrics': ctx,
        'ai_used': ai_used,
        'updated_at': _utcnow_iso(),
        'stale': False,
        'cache_age_seconds': 0,
    }
    _save_report(report)
    return report


def run_all_ops_agents(*, use_ai: bool | None = None, force: bool = False) -> dict[str, dict[str, Any]]:
    results: dict[str, dict[str, Any]] = {}
    for domain in VALID_DOMAINS:
        try:
            results[domain] = run_ops_agent(domain, force=force, use_ai=use_ai)
        except Exception as exc:
            logger.error('[ops_agents] Failed domain %s: %s', domain, exc)
            results[domain] = {
                'domain': domain,
                'agent_name': AGENT_META[domain]['name'],
                'status': 'critical',
                'summary': f'Agent run failed: {exc}',
                'findings': [],
                'actions': [],
                'updated_at': _utcnow_iso(),
            }
    return results


def execute_agent_action(
    domain: str,
    action_id: str,
    *,
    actor_user_id: int | None = None,
) -> tuple[bool, str]:
    """Run a whitelisted agent action (sync or via event bus)."""
    from utils.event_bus import event_bus_enabled, publish_agent_action

    action_id = (action_id or '').strip()
    if domain not in VALID_DOMAINS or not action_id:
        return False, 'Invalid agent action.'

    if event_bus_enabled():
        msg_id = publish_agent_action(domain, action_id, actor_user_id=actor_user_id)
        if msg_id:
            return True, 'Action queued on the ops event bus.'

    return execute_agent_action_sync(domain, action_id, actor_user_id=actor_user_id)


def execute_agent_action_sync(
    domain: str,
    action_id: str,
    *,
    actor_user_id: int | None = None,
) -> tuple[bool, str]:
    """Run agent action synchronously (worker / fallback)."""
    action_id = (action_id or '').strip()
    if domain not in VALID_DOMAINS or not action_id:
        return False, 'Invalid agent action.'

    from utils.platform_ops_runs import complete_ops_run, start_ops_run

    run_id = start_ops_run(
        source=f'ceo_agent_{domain}_{action_id}',
        trigger='manual',
        actor_user_id=actor_user_id,
    )
    try:
        ok, message = _execute_agent_action_impl(domain, action_id, actor_user_id=actor_user_id)
        complete_ops_run(
            run_id,
            status='healthy' if ok else 'failed',
            result={'domain': domain, 'action_id': action_id, 'message': message},
        )
        return ok, message
    except Exception as exc:
        complete_ops_run(
            run_id,
            status='failed',
            result={'domain': domain, 'action_id': action_id, 'error': str(exc)},
        )
        raise


def _execute_agent_action_impl(
    domain: str,
    action_id: str,
    *,
    actor_user_id: int | None = None,
) -> tuple[bool, str]:
    try:
        if action_id == 'scan':
            from utils.platform_ops_orchestrator import run_health_cycle

            result = run_health_cycle(source='ceo_agent', apply_safe=False, blocking_lock=True)
            monitor = result.get('monitor') or {}
            return True, (
                f'DB scan complete — {monitor.get("issue_count", 0)} issue(s), '
                f'snapshot #{monitor.get("snapshot_id")}.'
            )

        if action_id == 'apply_safe':
            from utils.platform_ops_orchestrator import run_health_cycle

            result = run_health_cycle(source='ceo_apply', apply_safe=True, blocking_lock=True)
            indexes = result.get('indexes') or {}
            return True, (
                f'Applied {indexes.get("applied", 0)} safe fix(es), '
                f'{indexes.get("failed", 0)} failed.'
            )

        if action_id == 'run_maintenance':
            from utils.platform_ops import run_full_platform_ops

            result = run_full_platform_ops(actor_user_id=actor_user_id)
            return result.get('status') != 'failed', f'Maintenance finished: {result.get("status")}.'

        if action_id == 'bootstrap':
            from utils.mongo_platform import bootstrap_mongo

            result = bootstrap_mongo(provision_tenants=True)
            ok = all(s.get('ok', False) for s in result.get('steps', []))
            return ok, 'MongoDB tenant sync completed.' if ok else 'MongoDB sync completed with errors.'

        if action_id == 'sync_indexes':
            from mongodb_operations import get_mongo_connection
            from utils.mongo_catalog import apply_catalog_indexes

            _, mongo_db, _ = get_mongo_connection()
            if mongo_db is None:
                return False, 'MongoDB unavailable.'
            apply_catalog_indexes(mongo_db)
            return True, 'MongoDB catalog indexes applied.'

        if action_id == 'refresh':
            if domain == 'ai':
                from utils.ai_platform import bootstrap_ai

                bootstrap_ai()
                return True, 'AI engine status refreshed.'
            run_ops_agent(domain, force=True, use_ai=False)
            return True, f'{AGENT_META[domain]["name"]} metrics refreshed.'

        if action_id == 'clear_expired':
            from utils.ai_platform import clear_ai_cache

            result = clear_ai_cache(expired_only=True)
            return result.get('ok', False), f'Removed {result.get("removed", 0)} expired cache file(s).'

        if action_id == 'trim_cache':
            from utils import ai_cache

            result = ai_cache.trim_to_capacity()
            return True, f'Trimmed {result.get("removed", 0)} cache file(s).'

        if action_id == 'recheck':
            run_ops_agent('integrations', force=True, use_ai=False)
            return True, 'Integration checks refreshed.'

        if action_id == 'refresh_all':
            run_all_ops_agents(use_ai=False, force=True)
            return True, 'All ops agents refreshed.'

        return False, f'Unknown action: {action_id}'
    except Exception as exc:
        logger.error('[ops_agents] action %s/%s failed: %s', domain, action_id, exc)
        return False, str(exc)
    finally:
        if action_id in ('scan', 'apply_safe', 'run_maintenance'):
            try:
                from utils.platform_ops import invalidate_ops_read_caches

                invalidate_ops_read_caches()
            except Exception:
                pass
        try:
            run_ops_agent(domain, force=True, use_ai=USE_AI_DEFAULT)
        except Exception:
            pass
