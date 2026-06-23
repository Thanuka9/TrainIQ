"""Safe tenant ORM loads with deadlock retry (used on every request)."""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from models import Tenant


def _request_tenant_cache() -> dict | None:
    try:
        from flask import g, has_request_context
    except ImportError:
        return None
    if not has_request_context():
        return None
    cache = getattr(g, '_tenant_by_id_cache', None)
    if cache is None:
        g._tenant_by_id_cache = {}
        cache = g._tenant_by_id_cache
    return cache


def load_tenant_by_id(tenant_id: int | None, *, label: str = 'tenant_by_id') -> 'Tenant | None':
    if not tenant_id:
        return None

    cache = _request_tenant_cache()
    if cache is not None and tenant_id in cache:
        return cache[tenant_id]

    from extensions import db
    from models import Tenant
    from utils.db_retry import run_with_db_retry

    def _load():
        return db.session.get(Tenant, tenant_id)

    try:
        tenant = run_with_db_retry(_load, rollback=db.session.rollback, label=label)
    except Exception:
        db.session.rollback()
        tenant = None

    if cache is not None:
        cache[tenant_id] = tenant
    return tenant


def invalidate_request_tenant_cache(tenant_id: int | None = None) -> None:
    """Drop cached tenant row(s) after updates in the same request."""
    cache = _request_tenant_cache()
    if cache is None:
        return
    if tenant_id is None:
        cache.clear()
    else:
        cache.pop(tenant_id, None)


def load_tenants_with_allowed_domains(*, label: str = 'tenant_domain_list') -> list:
    from extensions import db
    from models import Tenant
    from utils.db_retry import run_with_db_retry

    def _load():
        return Tenant.query.filter(Tenant.allowed_domain.isnot(None)).all()

    try:
        return run_with_db_retry(_load, rollback=db.session.rollback, label=label)
    except Exception:
        db.session.rollback()
        return []


def load_user_by_id(user_id: int | str | None, *, label: str = 'user_by_id'):
    if user_id is None:
        return None
    from extensions import db
    from models import User
    from utils.db_retry import run_with_db_retry

    def _load():
        return db.session.get(User, int(user_id))

    try:
        return run_with_db_retry(_load, rollback=db.session.rollback, label=label)
    except Exception:
        db.session.rollback()
        return None


def run_db_read(fn, *, label: str = 'db_read', attempts: int = 3):
    """Run a read-only ORM callable with deadlock retry + session rollback."""
    from extensions import db
    from utils.db_retry import run_with_db_retry

    try:
        return run_with_db_retry(
            fn,
            rollback=db.session.rollback,
            label=label,
            attempts=attempts,
        )
    except Exception:
        db.session.rollback()
        raise
