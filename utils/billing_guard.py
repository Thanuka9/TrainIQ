"""Billing guards — duplicate payment prevention and idempotent plan upgrades."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from utils.billing_plans import PLAN_ORDER, TRIAL_DAYS, get_plan

logger = logging.getLogger(__name__)

PENDING_CHECKOUT_TTL_HOURS = 2


def billing_period_end_for(start: datetime, billing_cycle: str) -> datetime:
    cycle = (billing_cycle or "monthly").lower()
    if cycle == "yearly":
        return start + timedelta(days=365)
    return start + timedelta(days=30)


def tenant_in_active_paid_period(tenant) -> bool:
    if not tenant:
        return False
    plan = (getattr(tenant, "plan", "") or "trial").lower()
    if plan in ("trial", "enterprise"):
        return plan == "enterprise" and (getattr(tenant, "status", "") or "").lower() == "active"
    status = (getattr(tenant, "status", "") or "").lower()
    if status not in ("active",):
        return False
    period_end = getattr(tenant, "billing_period_end", None)
    if period_end:
        return datetime.utcnow() < period_end
    # Legacy paid tenants without period dates — treat as active if not trial
    return plan not in ("trial",)


def _plan_rank(plan_id: str) -> int:
    try:
        return PLAN_ORDER.index((plan_id or "trial").lower())
    except ValueError:
        return -1


def evaluate_upgrade(tenant, plan_id: str, billing_cycle: str) -> dict[str, Any]:
    """
    Decide whether a payment or plan change should proceed.
    Returns dict: ok, message, reason, is_duplicate, is_upgrade, is_downgrade
    """
    plan_id = (plan_id or "").strip().lower()
    billing_cycle = (billing_cycle or "monthly").strip().lower()
    current_plan = (getattr(tenant, "plan", "") or "trial").lower()
    current_cycle = (getattr(tenant, "billing_cycle", "") or "monthly").lower()
    active_paid = tenant_in_active_paid_period(tenant)

    result = {
        "ok": True,
        "message": "",
        "reason": "",
        "is_duplicate": False,
        "is_upgrade": _plan_rank(plan_id) > _plan_rank(current_plan),
        "is_downgrade": _plan_rank(plan_id) < _plan_rank(current_plan),
    }

    if plan_id == "trial":
        result.update(ok=False, message="Select a paid plan to upgrade.", reason="trial_selected")
        return result

    plan = get_plan(plan_id)
    if plan.get("contact_sales"):
        result.update(ok=False, message="Contact sales for Enterprise pricing.", reason="enterprise")
        return result

    if not active_paid:
        return result

    period_end = getattr(tenant, "billing_period_end", None)
    period_label = period_end.strftime("%b %d, %Y") if period_end else "the current period"

    # Exact duplicate: same plan + cycle within active billing period
    if current_plan == plan_id and current_cycle == billing_cycle:
        result.update(
            ok=False,
            is_duplicate=True,
            reason="duplicate_subscription",
            message=(
                f"Your organization is already on {plan['name']} ({billing_cycle}) "
                f"through {period_label}. No additional payment is required."
            ),
        )
        return result

    # Downgrade during active period
    if result["is_downgrade"]:
        result.update(
            ok=False,
            reason="downgrade_blocked",
            message=(
                f"Downgrades take effect at the next renewal ({period_label}). "
                "Contact support if you need help changing plans."
            ),
        )
        return result

    # Lateral move: different cycle, same tier — block double charge
    if current_plan == plan_id and current_cycle != billing_cycle:
        result.update(
            ok=False,
            reason="cycle_change_blocked",
            message=(
                f"Billing cycle changes are applied at renewal ({period_label}). "
                "Contact support to switch between monthly and yearly billing."
            ),
        )
        return result

    return result


def _billing_event_exists(**filters) -> bool:
    from models import BillingEvent

    q = BillingEvent.query
    for key, val in filters.items():
        if val is not None:
            q = q.filter(getattr(BillingEvent, key) == val)
    return q.first() is not None


def record_billing_event(
    *,
    tenant,
    plan_id: str,
    billing_cycle: str,
    source: str,
    status: str = "applied",
    idempotency_key: str,
    amount_cents: int | None = None,
    stripe_event_id: str | None = None,
    stripe_session_id: str | None = None,
    stripe_subscription_id: str | None = None,
    billing_period_start: datetime | None = None,
    billing_period_end: datetime | None = None,
    details: str | None = None,
):
    from extensions import db
    from models import BillingEvent
    from sqlalchemy.exc import IntegrityError

    existing = BillingEvent.query.filter_by(idempotency_key=idempotency_key).first()
    if existing:
        return existing, False

    if stripe_event_id and _billing_event_exists(stripe_event_id=stripe_event_id):
        dup = BillingEvent.query.filter_by(stripe_event_id=stripe_event_id).first()
        return dup, False

    if stripe_session_id and _billing_event_exists(stripe_session_id=stripe_session_id):
        dup = BillingEvent.query.filter_by(stripe_session_id=stripe_session_id).first()
        return dup, False

    event = BillingEvent(
        tenant_id=tenant.id,
        idempotency_key=idempotency_key,
        source=source,
        status=status,
        plan_id=plan_id,
        billing_cycle=billing_cycle,
        amount_cents=amount_cents,
        stripe_event_id=stripe_event_id,
        stripe_session_id=stripe_session_id,
        stripe_subscription_id=stripe_subscription_id,
        billing_period_start=billing_period_start,
        billing_period_end=billing_period_end,
        details=details,
    )
    db.session.add(event)
    try:
        db.session.flush()
    except IntegrityError:
        db.session.rollback()
        dup = BillingEvent.query.filter_by(idempotency_key=idempotency_key).first()
        return dup, False
    return event, True


def has_pending_checkout(tenant, plan_id: str, billing_cycle: str) -> bool:
    from models import BillingEvent

    cutoff = datetime.utcnow() - timedelta(hours=PENDING_CHECKOUT_TTL_HOURS)
    return (
        BillingEvent.query.filter_by(
            tenant_id=tenant.id,
            plan_id=plan_id,
            billing_cycle=billing_cycle,
            status="pending",
            source="checkout_pending",
        )
        .filter(BillingEvent.created_at >= cutoff)
        .first()
        is not None
    )


def apply_plan_upgrade(
    tenant,
    plan_id: str,
    *,
    billing_cycle: str = "monthly",
    source: str = "manual_upgrade",
    idempotency_key: str | None = None,
    stripe_event_id: str | None = None,
    stripe_session_id: str | None = None,
    stripe_subscription_id: str | None = None,
    amount_cents: int | None = None,
    force: bool = False,
) -> tuple[bool, str]:
    """
    Idempotent plan upgrade with duplicate-payment protection.
    Returns (success, message).
    """
    from utils.billing_plans import apply_paid_plan

    plan_id = (plan_id or "").strip().lower()
    billing_cycle = (billing_cycle or "monthly").strip().lower()

    if not idempotency_key:
        if stripe_event_id:
            idempotency_key = f"stripe_event:{stripe_event_id}"
        elif stripe_session_id:
            idempotency_key = f"stripe_session:{stripe_session_id}"
        else:
            period_key = datetime.utcnow().strftime("%Y-%m")
            idempotency_key = f"manual:{tenant.id}:{plan_id}:{billing_cycle}:{period_key}"

    from models import BillingEvent

    existing = BillingEvent.query.filter_by(idempotency_key=idempotency_key).first()
    if existing and existing.status == "applied":
        return True, "Payment already processed for this billing period."

    if not force:
        decision = evaluate_upgrade(tenant, plan_id, billing_cycle)
        if not decision["ok"]:
            if decision.get("is_duplicate") and stripe_event_id:
                record_billing_event(
                    tenant=tenant,
                    plan_id=plan_id,
                    billing_cycle=billing_cycle,
                    source=source,
                    status="duplicate",
                    idempotency_key=idempotency_key or f"dup:{stripe_event_id}",
                    stripe_event_id=stripe_event_id,
                    stripe_session_id=stripe_session_id,
                    details=decision["message"],
                )
            return False, decision["message"]

    ok, msg = apply_paid_plan(tenant, plan_id, billing_cycle=billing_cycle)
    if not ok:
        return False, msg

    now = datetime.utcnow()
    period_start = now
    period_end = billing_period_end_for(now, billing_cycle)
    tenant.billing_period_start = period_start
    tenant.billing_period_end = period_end
    if stripe_subscription_id:
        tenant.stripe_subscription_id = stripe_subscription_id

    _, created = record_billing_event(
        tenant=tenant,
        plan_id=plan_id,
        billing_cycle=billing_cycle,
        source=source,
        status="applied",
        idempotency_key=idempotency_key,
        amount_cents=amount_cents,
        stripe_event_id=stripe_event_id,
        stripe_session_id=stripe_session_id,
        stripe_subscription_id=stripe_subscription_id,
        billing_period_start=period_start,
        billing_period_end=period_end,
        details=msg,
    )
    if not created and existing and existing.status == "applied":
        return True, "Payment already processed for this billing period."

    return True, msg


def mark_checkout_pending(tenant, plan_id: str, billing_cycle: str, session_id: str) -> None:
    from extensions import db

    record_billing_event(
        tenant=tenant,
        plan_id=plan_id,
        billing_cycle=billing_cycle,
        source="checkout_pending",
        status="pending",
        idempotency_key=f"checkout_pending:{session_id}",
        stripe_session_id=session_id,
        details="Stripe checkout session created",
    )
    db.session.commit()


def validate_checkout_start(tenant, plan_id: str, billing_cycle: str) -> tuple[bool, str]:
    decision = evaluate_upgrade(tenant, plan_id, billing_cycle)
    if not decision["ok"]:
        return False, decision["message"]
    if has_pending_checkout(tenant, plan_id, billing_cycle):
        return False, (
            "A checkout for this plan is already in progress. "
            "Complete or cancel it before starting another payment."
        )
    return True, ""
