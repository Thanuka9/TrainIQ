"""TrainIQ SaaS plan catalog — user-based packages and trial limits.

Pricing rationale (2025–2026 LMS market):
- Mid-market SaaS LMS: ~$3–15 per registered user/month (tiered packages).
- TrainIQ includes AI Q&A, exams, proctoring, and multi-tenant isolation — priced
  at a premium vs basic LMS while staying competitive via user-band tiers.

Trial: 30 days, 10 users — enough for admin + HR + a learner pilot team (team
products convert better with ~10 seats than 5; caps abuse vs unlimited trial).
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta
from typing import Any

TRIAL_DAYS = int(os.getenv("TRAINIQ_TRIAL_DAYS", "30"))
TRIAL_MAX_USERS = int(os.getenv("TRAINIQ_TRIAL_MAX_USERS", "10"))

# plan_id -> definition (max_users is hard cap for the package)
PLANS: dict[str, dict[str, Any]] = {
    "trial": {
        "id": "trial",
        "name": "Free Trial",
        "tagline": "Full platform access for 30 days",
        "max_users": TRIAL_MAX_USERS,
        "max_storage_mb": 2048,
        "price_monthly": 0,
        "price_yearly_per_month": 0,
        "trial_days": TRIAL_DAYS,
        "public": False,
        "contact_sales": False,
        "features": [
            f"Up to {TRIAL_MAX_USERS} team members",
            f"{TRIAL_DAYS}-day full feature access",
            "AI-powered course Q&A (LearnIQ)",
            "Exams with ProctorIQ",
            "Invite-only or domain signup",
        ],
        "sort_order": 0,
    },
    "starter": {
        "id": "starter",
        "name": "Starter",
        "tagline": "Small teams building their first training program",
        "max_users": 20,
        "max_storage_mb": 5120,
        "price_monthly": 49,
        "price_yearly_per_month": 39,
        "public": True,
        "contact_sales": False,
        "popular": False,
        "features": [
            "Up to 20 team members",
            "5 GB document storage",
            "Courses, exams & tasks",
            "Basic proctoring",
            "Email support",
        ],
        "sort_order": 1,
    },
    "growth": {
        "id": "growth",
        "name": "Growth",
        "tagline": "Scaling teams that need analytics and branding",
        "max_users": 75,
        "max_storage_mb": 25600,
        "price_monthly": 149,
        "price_yearly_per_month": 119,
        "public": True,
        "contact_sales": False,
        "popular": True,
        "features": [
            "Up to 75 team members",
            "25 GB document storage",
            "White-label branding",
            "Full audit logs & reports",
            "Priority support (24h SLA)",
        ],
        "sort_order": 2,
    },
    "business": {
        "id": "business",
        "name": "Business",
        "tagline": "Larger organizations with advanced training needs",
        "max_users": 200,
        "max_storage_mb": 102400,
        "price_monthly": 349,
        "price_yearly_per_month": 279,
        "public": True,
        "contact_sales": False,
        "features": [
            "Up to 200 team members",
            "100 GB document storage",
            "Dedicated onboarding",
            "Custom catalog & roles",
            "Phone + priority support",
        ],
        "sort_order": 3,
    },
    "enterprise": {
        "id": "enterprise",
        "name": "Enterprise",
        "tagline": "Custom scale, SLAs, and integrations",
        "max_users": 10000,
        "max_storage_mb": 512000,
        "price_monthly": None,
        "price_yearly_per_month": None,
        "public": True,
        "contact_sales": True,
        "features": [
            "Unlimited users (custom contract)",
            "Dedicated MongoDB tenant bucket",
            "SSO / SCIM (on request)",
            "Custom integrations & API",
            "Dedicated account engineer",
        ],
        "sort_order": 4,
    },
}

PLAN_ORDER = ("trial", "starter", "growth", "business", "enterprise")
UPGRADEABLE_PLAN_IDS = ("starter", "growth", "business", "enterprise")
SALES_EMAIL = os.getenv("TRAINIQ_SALES_EMAIL", "support@trainiq.com")


def get_plan(plan_id: str | None) -> dict[str, Any]:
    key = (plan_id or "trial").strip().lower()
    return PLANS.get(key, PLANS["trial"]).copy()


def plan_effective_per_user(plan_id: str, billing_cycle: str = "monthly") -> float | None:
    """Transparent per-seat price (TalentLMS-style) for marketing."""
    plan = get_plan(plan_id)
    if plan.get("contact_sales") or not plan.get("price_monthly"):
        return None
    price = plan["price_yearly_per_month"] if billing_cycle == "yearly" else plan["price_monthly"]
    cap = plan.get("max_users") or 1
    return round(price / cap, 2)


def get_public_plans() -> list[dict[str, Any]]:
    plans = sorted(
        [p.copy() for p in PLANS.values() if p.get("public")],
        key=lambda x: x.get("sort_order", 99),
    )
    for p in plans:
        p["effective_per_user_monthly"] = plan_effective_per_user(p["id"], "monthly")
        p["effective_per_user_yearly"] = plan_effective_per_user(p["id"], "yearly")
    return plans


def plan_display_price(plan_id: str, billing_cycle: str = "monthly") -> str:
    plan = get_plan(plan_id)
    if plan.get("contact_sales"):
        return "Custom"
    if plan.get("price_monthly") == 0:
        return "Free"
    if billing_cycle == "yearly":
        return f"${plan['price_yearly_per_month']}"
    return f"${plan['price_monthly']}"


def apply_trial_to_tenant(tenant) -> None:
    """New organizations start on a 30-day trial (10 users)."""
    plan = PLANS["trial"]
    tenant.plan = "trial"
    tenant.status = "trial"
    tenant.max_users = plan["max_users"]
    tenant.max_storage_mb = plan["max_storage_mb"]
    tenant.trial_ends_at = datetime.utcnow() + timedelta(days=TRIAL_DAYS)


def apply_paid_plan(tenant, plan_id: str, *, billing_cycle: str = "monthly") -> tuple[bool, str]:
    """Apply a paid package to a tenant (upgrade / plan change)."""
    plan = get_plan(plan_id)
    if plan_id == "trial":
        return False, "Select a paid plan to upgrade."
    if plan.get("contact_sales"):
        return False, "Contact sales for Enterprise pricing."

    from utils.tenant_limits import tenant_user_count

    users = tenant_user_count(tenant.id)
    if users > plan["max_users"]:
        return (
            False,
            f"Your organization has {users} users. {plan['name']} supports up to "
            f"{plan['max_users']}. Remove users or choose a higher plan.",
        )

    tenant.plan = plan_id
    tenant.status = "active"
    tenant.max_users = plan["max_users"]
    tenant.max_storage_mb = plan["max_storage_mb"]
    tenant.trial_ends_at = None
    tenant.trial_reminder_7d_at = None
    tenant.trial_reminder_1d_at = None
    tenant.billing_cycle = billing_cycle
    return True, f"Plan updated to {plan['name']}."


def backfill_missing_trial_dates() -> int:
    """Set trial_ends_at on legacy trial tenants that were created before trial tracking."""
    from extensions import db
    from models import Tenant

    updated = 0
    tenants = Tenant.query.filter(
        Tenant.plan == "trial",
        Tenant.trial_ends_at.is_(None),
    ).all()
    for tenant in tenants:
        base = getattr(tenant, "created_at", None) or datetime.utcnow()
        tenant.trial_ends_at = base + timedelta(days=TRIAL_DAYS)
        status = (getattr(tenant, "status", "") or "").lower()
        if status not in ("expired", "suspended"):
            tenant.status = "trial"
        if not tenant.max_users or tenant.max_users > TRIAL_MAX_USERS:
            tenant.max_users = TRIAL_MAX_USERS
        updated += 1
    if updated:
        db.session.commit()
    return updated


def trial_days_remaining(tenant) -> int | None:
    if not tenant or not getattr(tenant, "trial_ends_at", None):
        return None
    if (getattr(tenant, "plan", "") or "").lower() != "trial":
        return None
    delta = tenant.trial_ends_at - datetime.utcnow()
    return max(0, delta.days + (1 if delta.seconds > 0 else 0))


def is_trial_expired(tenant) -> bool:
    if not tenant:
        return True
    if (getattr(tenant, "plan", "") or "").lower() != "trial":
        return False
    ends = getattr(tenant, "trial_ends_at", None)
    if not ends:
        return False
    return datetime.utcnow() > ends


def tenant_usage(tenant) -> dict[str, Any]:
    from utils.tenant_limits import tenant_user_count

    users = tenant_user_count(tenant.id) if tenant else 0
    max_users = getattr(tenant, "max_users", None) or PLANS["trial"]["max_users"]
    plan = get_plan(getattr(tenant, "plan", None))
    remaining = max(0, max_users - users)
    at_limit = users >= max_users
    pct = min(100, int((users / max_users) * 100)) if max_users else 0
    return {
        "users": users,
        "max_users": max_users,
        "remaining_seats": remaining,
        "at_limit": at_limit,
        "usage_percent": pct,
        "plan": plan,
        "trial_days_left": trial_days_remaining(tenant),
        "trial_expired": is_trial_expired(tenant),
    }


def next_upgrade_plan(tenant) -> dict[str, Any] | None:
    """Suggest the next package when at user limit."""
    current = (getattr(tenant, "plan", None) or "trial").lower()
    try:
        idx = PLAN_ORDER.index(current)
    except ValueError:
        idx = 0
    for pid in PLAN_ORDER[idx + 1 :]:
        if pid == "enterprise":
            return get_plan("enterprise")
        p = get_plan(pid)
        from utils.tenant_limits import tenant_user_count
        if tenant_user_count(tenant.id) < p["max_users"]:
            return p
    return get_plan("enterprise")


PLAN_COMPARISON_COLUMNS = ("starter", "growth", "business", "enterprise")

FEATURE_COMPARISON: list[dict[str, Any]] = [
    {
        "label": "Team members",
        "starter": "20",
        "growth": "75",
        "business": "200",
        "enterprise": "Custom",
    },
    {
        "label": "Document storage",
        "starter": "5 GB",
        "growth": "25 GB",
        "business": "100 GB",
        "enterprise": "500 GB+",
    },
    {
        "label": "Courses & study materials",
        "starter": True,
        "growth": True,
        "business": True,
        "enterprise": True,
    },
    {
        "label": "Proctored exams (ProctorIQ)",
        "starter": True,
        "growth": True,
        "business": True,
        "enterprise": True,
    },
    {
        "label": "AI course Q&A (LearnIQ)",
        "starter": True,
        "growth": True,
        "business": True,
        "enterprise": True,
    },
    {
        "label": "Tasks & assignments",
        "starter": True,
        "growth": True,
        "business": True,
        "enterprise": True,
    },
    {
        "label": "White-label branding",
        "starter": False,
        "growth": True,
        "business": True,
        "enterprise": True,
    },
    {
        "label": "Audit logs & custom reports",
        "starter": False,
        "growth": True,
        "business": True,
        "enterprise": True,
    },
    {
        "label": "Invite-only registration",
        "starter": True,
        "growth": True,
        "business": True,
        "enterprise": True,
    },
    {
        "label": "Dedicated onboarding",
        "starter": False,
        "growth": False,
        "business": True,
        "enterprise": True,
    },
    {
        "label": "Per-tenant data isolation",
        "starter": True,
        "growth": True,
        "business": True,
        "enterprise": True,
    },
    {
        "label": "SSO / SCIM",
        "starter": False,
        "growth": False,
        "business": False,
        "enterprise": True,
    },
    {
        "label": "Support",
        "starter": "Email",
        "growth": "24h priority",
        "business": "Phone + priority",
        "enterprise": "Dedicated engineer",
    },
]


def get_feature_comparison() -> dict[str, Any]:
    """Docebo-style plan comparison matrix for /pricing."""
    columns = [
        {"id": pid, "name": get_plan(pid)["name"]}
        for pid in PLAN_COMPARISON_COLUMNS
    ]
    return {"columns": columns, "rows": FEATURE_COMPARISON}
