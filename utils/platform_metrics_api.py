"""JSON-safe metrics payload for Operations live polling (Redis-cacheable)."""
from __future__ import annotations

import os
from typing import Any


def _ops_cache_ttl() -> float:
    return max(5.0, float(os.getenv('OPS_METRICS_CACHE_SECONDS', '15')))


def build_metrics_api_payload() -> dict[str, Any]:
    """Collect ops metrics as a JSON-serializable dict."""
    try:
        import psutil
        cpu_percent = psutil.cpu_percent()
        mem = psutil.virtual_memory()
        mem_percent = mem.percent
        mem_used = int(mem.used / (1024 * 1024))
        mem_total = int(mem.total / (1024 * 1024))
    except ImportError:
        cpu_percent = mem_percent = mem_used = mem_total = None

    from utils.platform_ops import get_platform_ops_status

    ops = get_platform_ops_status(cache_seconds=0)
    page = ops.get('postgres', {}).get('page') or {}
    snapshot = page.get('snapshot')
    pg_stats = page.get('postgres_stats') or {}
    capacity = pg_stats.get('capacity') or {}
    connections = capacity.get('connections') or {}

    int_ok = len([c for c in ops.get('integrations', {}).get('checks', []) if c.get('ok')])
    int_total = len(ops.get('integrations', {}).get('checks', []))

    migration = ops.get('postgres', {}).get('migration') or {}
    from utils.stripe_billing import stripe_available
    from utils.prometheus_metrics import metrics_enabled

    return {
        'status': ops.get('status'),
        'billing': {
            'stripe_configured': stripe_available(),
        },
        'observability': {
            'prometheus_enabled': metrics_enabled(),
        },
        'postgres': {
            'pending': migration.get('pending'),
            'migration_head': migration.get('head'),
            'issue_count': getattr(snapshot, 'issue_count', 0) if snapshot else 0,
            'recommendation_count': getattr(snapshot, 'recommendation_count', 0) if snapshot else 0,
            'database_size_mb': capacity.get('database_size_mb'),
            'cache_hit_ratio': capacity.get('cache_hit_ratio'),
            'connections_active': connections.get('active'),
            'connections_max': connections.get('max'),
        },
        'mongo': {
            'available': ops.get('mongo', {}).get('available'),
            'tenant_db_count': ops.get('mongo', {}).get('tenant_db_count', 0),
            'unprovisioned_tenants': ops.get('mongo', {}).get('unprovisioned_tenants', 0),
        },
        'ai': {
            'available': ops.get('ai', {}).get('available', False),
            'model_ready': ops.get('ai', {}).get('model_ready', False),
            'resolved_model': ops.get('ai', {}).get('resolved_model', ''),
            'cache_files': ops.get('ai', {}).get('cache', {}).get('files', 0),
        },
        'integrations': {'ok': int_ok, 'total': int_total},
        'system': {
            'cpu_percent': cpu_percent,
            'mem_percent': mem_percent,
            'mem_used_mb': mem_used,
            'mem_total_mb': mem_total,
        },
    }


def get_cached_metrics_api_payload() -> dict[str, Any]:
    from utils.ops_cache import get_json_cached

    return get_json_cached('metrics_api', _ops_cache_ttl(), build_metrics_api_payload)
