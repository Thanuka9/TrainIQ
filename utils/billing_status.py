"""Tenant billing status helpers (past_due grace, payment warnings)."""
from __future__ import annotations


def tenant_status(tenant) -> str:
    return (getattr(tenant, 'status', None) or 'active').lower()


def tenant_is_past_due(tenant) -> bool:
    return tenant_status(tenant) == 'past_due'


def user_can_access_past_due_org(user) -> bool:
    """Billing admins may access org during Stripe past_due grace."""
    if not user:
        return False
    if getattr(user, 'is_super_admin', False):
        return True
    try:
        from utils.admin_permissions import user_has_permission

        return user_has_permission(user, 'org.billing')
    except Exception:
        return False


def past_due_login_allowed(tenant, user) -> tuple[bool, str]:
    if not tenant_is_past_due(tenant):
        return True, ''
    if user_can_access_past_due_org(user):
        return True, 'past_due'
    return (
        False,
        'Your organization has a failed payment. Ask a Super Admin to update billing in Stripe.',
    )


def past_due_warning_message(tenant) -> str:
    return (
        f'Payment failed for {getattr(tenant, "name", "your organization")}. '
        'Update your payment method in Billing to avoid service interruption.'
    )
