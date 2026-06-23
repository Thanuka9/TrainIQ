"""Shared billing context for templates and routes."""
from __future__ import annotations


def get_active_tenant_usage(user=None):
    """Return (tenant, usage dict) for the active tenant session, or (None, None)."""
    from flask_login import current_user
    from utils.billing_plans import tenant_usage
    from utils.tenant_utils import user_tenant_id

    user = user or current_user
    if not user or not getattr(user, "is_authenticated", False) or not user.is_authenticated:
        return None, None
    tid = user_tenant_id()
    if not tid:
        return None, None
    from utils.tenant_db import load_tenant_by_id

    tenant = load_tenant_by_id(tid, label='billing_context')
    if not tenant:
        return None, None
    return tenant, tenant_usage(tenant)
