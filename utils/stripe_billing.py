"""Stripe Checkout foundation (optional — requires STRIPE_SECRET_KEY)."""
from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "").strip()
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "").strip()
STRIPE_ENABLED = bool(STRIPE_SECRET_KEY)


def stripe_available() -> bool:
    return STRIPE_ENABLED


def _plan_amount_cents(plan: dict, billing_cycle: str) -> int | None:
    cycle = (billing_cycle or "monthly").lower()
    if cycle == "yearly":
        monthly = plan.get("price_yearly_per_month")
        if monthly is None:
            return None
        return int(float(monthly) * 12 * 100)
    monthly = plan.get("price_monthly")
    if monthly is None:
        return None
    return int(float(monthly) * 100)


def create_checkout_session(*, tenant, plan_id: str, billing_cycle: str, success_url: str, cancel_url: str):
    """
    Create a Stripe Checkout session for plan upgrade.
    Returns (session_id, checkout_url) or (None, None) if Stripe is not configured.
    """
    if not STRIPE_ENABLED:
        return None, None

    try:
        import stripe  # type: ignore

        stripe.api_key = STRIPE_SECRET_KEY
        from utils.billing_plans import get_plan

        plan = get_plan(plan_id)
        amount_cents = _plan_amount_cents(plan, billing_cycle)
        if not amount_cents or amount_cents <= 0:
            logger.warning("Stripe checkout skipped — no price for plan %s/%s", plan_id, billing_cycle)
            return None, None

        customer_id = getattr(tenant, "stripe_customer_id", None)
        if not customer_id:
            customer = stripe.Customer.create(
                email=tenant.billing_email or None,
                name=tenant.name,
                metadata={"tenant_id": str(tenant.id), "office_key": tenant.office_key or ""},
            )
            customer_id = customer.id
            tenant.stripe_customer_id = customer_id

        idempotency_key = (
            f"checkout-{tenant.id}-{plan_id}-{billing_cycle}-"
            f"{getattr(tenant, 'billing_period_end', '') or 'new'}"
        )

        session = stripe.checkout.Session.create(
            mode="subscription",
            customer=customer_id,
            line_items=[{
                "price_data": {
                    "currency": "usd",
                    "unit_amount": amount_cents,
                    "recurring": {"interval": "year" if billing_cycle == "yearly" else "month"},
                    "product_data": {"name": f"TrainIQ {plan.get('name', plan_id)}"},
                },
                "quantity": 1,
            }],
            success_url=success_url + "?session_id={CHECKOUT_SESSION_ID}",
            cancel_url=cancel_url,
            metadata={
                "tenant_id": str(tenant.id),
                "plan_id": plan_id,
                "billing_cycle": billing_cycle,
            },
            idempotency_key=idempotency_key[:255],
        )
        return session.id, session.url
    except Exception as exc:
        logger.exception("Stripe checkout session failed: %s", exc)
        return None, None


def handle_webhook_payload(payload: bytes, sig_header: str):
    """Verify and parse Stripe webhook; returns event dict or None."""
    if not STRIPE_ENABLED or not STRIPE_WEBHOOK_SECRET:
        return None
    try:
        import stripe  # type: ignore

        stripe.api_key = STRIPE_SECRET_KEY
        return stripe.Webhook.construct_event(payload, sig_header, STRIPE_WEBHOOK_SECRET)
    except Exception as exc:
        logger.warning("Stripe webhook verification failed: %s", exc)
        return None
