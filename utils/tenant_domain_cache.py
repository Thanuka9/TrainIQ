"""Redis/in-process cache for custom-domain → tenant resolution."""
from __future__ import annotations

import os
from types import SimpleNamespace
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from models import Tenant


def _cache_ttl() -> float:
    return max(30.0, float(os.getenv('PLATFORM_TENANT_DOMAIN_CACHE_SECONDS', '120')))


def _serialize_tenants(tenants: list) -> list[dict]:
    return [
        {'id': t.id, 'allowed_domain': t.allowed_domain or ''}
        for t in tenants
        if getattr(t, 'allowed_domain', None)
    ]


def _load_domain_rows_uncached() -> list[dict]:
    from utils.tenant_db import load_tenants_with_allowed_domains

    return _serialize_tenants(load_tenants_with_allowed_domains())


def _load_domain_rows() -> list[dict]:
    from utils.ops_cache import get_json_cached

    return get_json_cached('tenant_allowed_domains', _cache_ttl(), _load_domain_rows_uncached)


def _scan_host_for_tenant_id(host: str) -> int | None:
    from utils.tenant_utils import host_matches_allowed

    for row in _load_domain_rows():
        if host_matches_allowed(host, row.get('allowed_domain') or ''):
            return int(row['id'])
    return None


def invalidate_tenant_domain_cache() -> None:
    from utils.ops_cache import invalidate_json_cached

    invalidate_json_cached('tenant_allowed_domains')
    invalidate_json_cached(None)


def resolve_tenant_id_for_host(host: str) -> int | None:
    from utils.ops_cache import get_json_cached

    host = (host or '').split(':')[0].lower()
    if not host:
        return None

    def producer():
        return {'id': _scan_host_for_tenant_id(host)}

    data = get_json_cached(f'tenant_host:{host}', _cache_ttl(), producer)
    return data.get('id') if isinstance(data, dict) else None


def load_tenants_with_allowed_domains_cached() -> list['Tenant']:
    """Cached tenant rows for host matching (rehydrates via request-scoped id cache)."""
    from utils.tenant_db import load_tenant_by_id

    host = None
    try:
        from flask import has_request_context, request

        if has_request_context():
            host = request.host.split(':')[0].lower()
    except Exception:
        pass

    if host:
        tid = resolve_tenant_id_for_host(host)
        if tid:
            tenant = load_tenant_by_id(tid, label='tenant_domain_cache')
            if tenant:
                return [tenant]

    out = []
    for row in _load_domain_rows():
        tenant = load_tenant_by_id(int(row['id']), label='tenant_domain_cache')
        if tenant:
            out.append(tenant)
    return out


def lightweight_tenant_row(tenant_id: int, allowed_domain: str) -> SimpleNamespace:
    return SimpleNamespace(id=tenant_id, allowed_domain=allowed_domain)
