"""Tenant plan limits, trial expiry, and user-cap enforcement."""
from __future__ import annotations

from datetime import datetime

from flask import flash


def get_tenant_limits(tenant):
    from utils.billing_plans import get_plan

    if not tenant:
        return {}
    plan = get_plan(getattr(tenant, "plan", None))
    return {
        "plan": getattr(tenant, "plan", None) or "trial",
        "plan_name": plan.get("name", "Trial"),
        "status": getattr(tenant, "status", None) or "active",
        "max_users": getattr(tenant, "max_users", None) or plan.get("max_users", 10),
        "max_storage_mb": getattr(tenant, "max_storage_mb", None) or plan.get("max_storage_mb", 2048),
        "trial_ends_at": getattr(tenant, "trial_ends_at", None),
    }


def tenant_user_count(tenant_id: int) -> int:
    from models import User
    return User.query.filter_by(tenant_id=tenant_id).count()


def tenant_is_active(tenant) -> bool:
    """False when suspended or free trial has expired without upgrade."""
    from utils.billing_plans import is_trial_expired

    if not tenant:
        return False
    status = (getattr(tenant, "status", None) or "active").lower()
    if status == "suspended":
        return False
    if status == "expired":
        return False
    if status == "anonymized":
        return False
    if status == "past_due":
        return True
    if is_trial_expired(tenant):
        return False
    return status in ("active", "trial", "past_due")


def trial_expired_message(tenant) -> str:
    from utils.billing_plans import TRIAL_DAYS
    return (
        f"Your {TRIAL_DAYS}-day free trial has ended. "
        "Upgrade to a paid plan to restore access for your team."
    )


def can_tenant_add_user(tenant) -> tuple[bool, str]:
    if not tenant:
        return False, "Organization not found."
    if not tenant_is_active(tenant):
        from utils.billing_plans import is_trial_expired
        if is_trial_expired(tenant):
            return False, trial_expired_message(tenant)
        return False, "This organization account is suspended. Contact support."
    limits = get_tenant_limits(tenant)
    count = tenant_user_count(tenant.id)
    if count >= limits["max_users"]:
        plan_name = limits.get("plan_name", "your plan")
        return (
            False,
            f"User limit reached ({count}/{limits['max_users']} on {plan_name}). "
            "Upgrade your plan in Billing to add more team members.",
        )
    return True, ""


def assert_tenant_can_register(tenant) -> bool:
    ok, msg = can_tenant_add_user(tenant)
    if not ok:
        flash(msg, "error")
    return ok


def assert_tenant_can_invite(tenant) -> bool:
    ok, msg = can_tenant_add_user(tenant)
    if not ok:
        flash(msg, "error")
    return ok


def expire_overdue_trials() -> int:
    """Mark trial tenants past trial_ends_at as expired. Returns count updated."""
    from extensions import db
    from models import Tenant
    from utils.billing_plans import is_trial_expired

    now = datetime.utcnow()
    updated = 0
    tenants = Tenant.query.filter(
        Tenant.plan == "trial",
        Tenant.trial_ends_at.isnot(None),
        Tenant.trial_ends_at < now,
        Tenant.status != "expired",
    ).all()
    for tenant in tenants:
        if is_trial_expired(tenant):
            tenant.status = "expired"
            updated += 1
    if updated:
        db.session.commit()
    return updated
