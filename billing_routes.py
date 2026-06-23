"""Admin billing — plan selection and upgrades."""
from __future__ import annotations

import logging
from datetime import datetime
from functools import wraps

from flask import Blueprint, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from audit import log_event
from extensions import db
from models import Tenant
from utils.billing_plans import (
    SALES_EMAIL,
    TRIAL_DAYS,
    UPGRADEABLE_PLAN_IDS,
    get_plan,
    get_public_plans,
    tenant_usage,
)
from utils.billing_guard import apply_plan_upgrade, mark_checkout_pending, validate_checkout_start
from utils.stripe_billing import (
    create_billing_portal_session,
    create_checkout_session,
    handle_webhook_payload,
    stripe_available,
)
from utils.tenant_utils import user_tenant_id
from utils.user_agreement import agreement_context

billing_routes = Blueprint("billing_routes", __name__)
logger = logging.getLogger(__name__)


def super_admin_required(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        from admin_routes import _effective_super_admin
        from utils.admin_permissions import user_has_permission
        if _effective_super_admin():
            return func(*args, **kwargs)
        if user_has_permission(current_user, "org.billing"):
            return func(*args, **kwargs)
        flash("Only Super Admins can manage billing.", "error")
        return redirect(url_for("general_routes.dashboard"))
    return wrapper


def _current_tenant() -> Tenant | None:
    from utils.tenant_db import load_tenant_by_id

    return load_tenant_by_id(user_tenant_id(), label='billing_routes')


def _billing_terms_accepted() -> bool:
    return request.form.get("accept_billing_terms") in ("1", "on", "true", "yes")


def _require_billing_terms() -> bool:
    if _billing_terms_accepted():
        return True
    flash(
        "You must accept the subscription and non-refund billing terms before upgrading.",
        "error",
    )
    return False


@billing_routes.route("/admin/billing")
@login_required
@super_admin_required
def billing_home():
    tenant = _current_tenant()
    if not tenant:
        flash("No organization context.", "error")
        return redirect(url_for("general_routes.dashboard"))

    checkout_status = (request.args.get("checkout") or "").strip().lower()
    if checkout_status == "success":
        flash("Payment received. Your plan upgrade is being applied.", "success")
    elif checkout_status == "cancelled":
        flash("Checkout was cancelled. No charge was made.", "info")

    usage = tenant_usage(tenant)
    plans = get_public_plans()
    upgrade_hint = request.args.get("upgrade")
    return render_template(
        "admin_billing.html",
        tenant=tenant,
        usage=usage,
        plans=plans,
        sales_email=SALES_EMAIL,
        upgrade_hint=upgrade_hint,
        current_plan=get_plan(tenant.plan),
        stripe_enabled=stripe_available(),
        trial_days=TRIAL_DAYS,
        **agreement_context(),
    )


@billing_routes.route("/admin/billing/export-data.json")
@login_required
@super_admin_required
def billing_export_org_data():
    """JSON export of organization data (portability / GDPR support)."""
    from flask import jsonify

    tenant = _current_tenant()
    if not tenant:
        flash("No organization context.", "error")
        return redirect(url_for("general_routes.dashboard"))

    from utils.tenant_export import build_tenant_export

    payload = build_tenant_export(tenant.id)
    if not payload:
        flash("Could not build export.", "error")
        return redirect(url_for("billing_routes.billing_home"))
    log_event("ORG_DATA_EXPORT", user=current_user, tenant_id=tenant.id)
    return jsonify(payload)


@billing_routes.route("/admin/billing/upgrade", methods=["POST"])
@login_required
@super_admin_required
def billing_upgrade():
    tenant = _current_tenant()
    if not tenant:
        flash("No organization context.", "error")
        return redirect(url_for("general_routes.dashboard"))

    plan_id = (request.form.get("plan_id") or "").strip().lower()
    billing_cycle = (request.form.get("billing_cycle") or "monthly").strip().lower()
    if billing_cycle not in ("monthly", "yearly"):
        billing_cycle = "monthly"

    if plan_id not in UPGRADEABLE_PLAN_IDS:
        flash("Invalid plan selected.", "error")
        return redirect(url_for("billing_routes.billing_home"))

    plan = get_plan(plan_id)
    if plan.get("contact_sales"):
        flash(f"Contact {SALES_EMAIL} for Enterprise pricing.", "info")
        return redirect(url_for("billing_routes.billing_home"))

    if not _require_billing_terms():
        return redirect(url_for("billing_routes.billing_home", upgrade=1))

    ok, msg = apply_plan_upgrade(
        tenant,
        plan_id,
        billing_cycle=billing_cycle,
        source="manual_upgrade",
    )
    if not ok:
        flash(msg, "error")
        return redirect(url_for("billing_routes.billing_home"))

    try:
        db.session.commit()
        log_event("PLAN_UPGRADE", user=current_user, details=f"{plan_id}/{billing_cycle}")
        flash(msg + " Your new user limit is active immediately.", "success")
    except Exception as exc:
        db.session.rollback()
        logger.error("Plan upgrade failed: %s", exc)
        flash("Could not save plan change. Try again or contact support.", "error")

    return redirect(url_for("billing_routes.billing_home"))


@billing_routes.route("/admin/billing/checkout", methods=["POST"])
@login_required
@super_admin_required
def billing_checkout():
    """Create a Stripe Checkout session and redirect to payment."""
    tenant = _current_tenant()
    if not tenant:
        flash("No organization context.", "error")
        return redirect(url_for("general_routes.dashboard"))

    if not stripe_available():
        flash("Stripe billing is not configured. Use manual upgrade or contact support.", "info")
        return redirect(url_for("billing_routes.billing_home"))

    plan_id = (request.form.get("plan_id") or "").strip().lower()
    billing_cycle = (request.form.get("billing_cycle") or "monthly").strip().lower()
    if billing_cycle not in ("monthly", "yearly"):
        billing_cycle = "monthly"

    if plan_id not in UPGRADEABLE_PLAN_IDS:
        flash("Invalid plan selected.", "error")
        return redirect(url_for("billing_routes.billing_home"))

    plan = get_plan(plan_id)
    if plan.get("contact_sales"):
        flash(f"Contact {SALES_EMAIL} for Enterprise pricing.", "info")
        return redirect(url_for("billing_routes.billing_home"))

    if not _require_billing_terms():
        return redirect(url_for("billing_routes.billing_home", upgrade=1))

    allowed, block_msg = validate_checkout_start(tenant, plan_id, billing_cycle)
    if not allowed:
        flash(block_msg, "error")
        return redirect(url_for("billing_routes.billing_home", upgrade=1))

    success_url = url_for("billing_routes.billing_home", checkout="success", _external=True)
    cancel_url = url_for("billing_routes.billing_home", checkout="cancelled", _external=True)
    session_id, checkout_url = create_checkout_session(
        tenant=tenant,
        plan_id=plan_id,
        billing_cycle=billing_cycle,
        success_url=success_url,
        cancel_url=cancel_url,
    )
    if not checkout_url or not session_id:
        flash("Could not start Stripe checkout. Try manual upgrade or contact support.", "error")
        return redirect(url_for("billing_routes.billing_home"))

    mark_checkout_pending(tenant, plan_id, billing_cycle, session_id)
    return redirect(checkout_url)


@billing_routes.route("/admin/billing/portal", methods=["POST"])
@login_required
@super_admin_required
def billing_portal():
    """Redirect to Stripe Customer Portal when configured."""
    tenant = _current_tenant()
    if not tenant:
        flash("No organization context.", "error")
        return redirect(url_for("general_routes.dashboard"))
    if not stripe_available() or not getattr(tenant, "stripe_customer_id", None):
        flash("Stripe billing portal is not available for this organization.", "info")
        return redirect(url_for("billing_routes.billing_home"))
    return_url = url_for("billing_routes.billing_home", _external=True)
    portal_url = create_billing_portal_session(tenant=tenant, return_url=return_url)
    if not portal_url:
        flash("Could not open billing portal. Contact support.", "error")
        return redirect(url_for("billing_routes.billing_home"))
    return redirect(portal_url)


@billing_routes.route("/webhooks/stripe", methods=["POST"])
def stripe_webhook():
    """Stripe webhook — apply plan after successful checkout."""
    payload = request.get_data()
    sig_header = request.headers.get("Stripe-Signature", "")
    try:
        from utils.prometheus_metrics import inc_stripe_webhook
    except Exception:
        inc_stripe_webhook = None  # type: ignore

    event = handle_webhook_payload(payload, sig_header)
    if not event:
        if inc_stripe_webhook:
            inc_stripe_webhook("unknown", "failed")
        return jsonify({"error": "invalid webhook"}), 400

    event_type = event.get("type") or "unknown"

    try:
        event_id = event.get("id") or ""
        if event["type"] == "checkout.session.completed":
            sess = event["data"]["object"]
            if (sess.get("payment_status") or "").lower() not in ("paid", "no_payment_required"):
                logger.info("Stripe checkout session not paid — skipped: %s", sess.get("id"))
                return jsonify({"received": True, "skipped": "unpaid"}), 200

            metadata = sess.get("metadata") or {}
            tenant_id = int(metadata.get("tenant_id") or 0)
            plan_id = (metadata.get("plan_id") or "").strip().lower()
            billing_cycle = (metadata.get("billing_cycle") or "monthly").strip().lower()
            tenant = Tenant.query.get(tenant_id) if tenant_id else None
            if tenant and plan_id:
                customer_id = sess.get("customer")
                if customer_id:
                    tenant.stripe_customer_id = customer_id
                subscription_id = sess.get("subscription")
                session_id = sess.get("id")
                amount_cents = sess.get("amount_total")

                ok, msg = apply_plan_upgrade(
                    tenant,
                    plan_id,
                    billing_cycle=billing_cycle,
                    source="stripe_webhook",
                    idempotency_key=f"stripe_event:{event_id}" if event_id else None,
                    stripe_event_id=event_id or None,
                    stripe_session_id=session_id,
                    stripe_subscription_id=subscription_id,
                    amount_cents=amount_cents,
                )
                if ok:
                    db.session.commit()
                    log_event(
                        "STRIPE_PLAN_UPGRADE",
                        details=f"tenant={tenant.id} plan={plan_id}/{billing_cycle} session={session_id}",
                    )
                    if inc_stripe_webhook:
                        inc_stripe_webhook(event_type, "applied")
                else:
                    db.session.commit()
                    logger.warning("Stripe webhook plan apply skipped: %s", msg)
                    if inc_stripe_webhook:
                        inc_stripe_webhook(event_type, "skipped")

        elif event["type"] == "invoice.payment_failed":
            inv = event["data"]["object"]
            subscription_id = inv.get("subscription")
            customer_id = inv.get("customer")
            tenant = None
            if subscription_id:
                tenant = Tenant.query.filter_by(stripe_subscription_id=subscription_id).first()
            if not tenant and customer_id:
                tenant = Tenant.query.filter_by(stripe_customer_id=customer_id).first()
            if tenant:
                tenant.status = "past_due"
                db.session.commit()
                log_event("STRIPE_PAYMENT_FAILED", details=f"tenant={tenant.id} invoice={inv.get('id')}")
                if inc_stripe_webhook:
                    inc_stripe_webhook(event_type, "past_due")

        elif event["type"] == "customer.subscription.deleted":
            sub = event["data"]["object"]
            subscription_id = sub.get("id")
            tenant = Tenant.query.filter_by(stripe_subscription_id=subscription_id).first() if subscription_id else None
            if tenant:
                tenant.stripe_subscription_id = None
                tenant.plan = "trial"
                tenant.status = "expired"
                tenant.billing_period_end = None
                db.session.commit()
                log_event("STRIPE_SUBSCRIPTION_ENDED", details=f"tenant={tenant.id}")
                if inc_stripe_webhook:
                    inc_stripe_webhook(event_type, "downgraded")

        elif event["type"] == "customer.subscription.updated":
            sub = event["data"]["object"]
            subscription_id = sub.get("id")
            tenant = (
                Tenant.query.filter_by(stripe_subscription_id=subscription_id).first()
                if subscription_id
                else None
            )
            if tenant:
                stripe_status = (sub.get("status") or "").lower()
                if stripe_status in ("past_due", "unpaid"):
                    tenant.status = "past_due"
                elif stripe_status in ("active", "trialing"):
                    if (tenant.status or "").lower() == "past_due":
                        tenant.status = "active"
                db.session.commit()
                log_event(
                    "STRIPE_SUBSCRIPTION_UPDATED",
                    details=f"tenant={tenant.id} stripe_status={stripe_status}",
                )
                if inc_stripe_webhook:
                    inc_stripe_webhook(event_type, stripe_status or "updated")

        elif event["type"] == "invoice.payment_succeeded":
            inv = event["data"]["object"]
            invoice_id = inv.get("id")
            if not invoice_id:
                return jsonify({"received": True}), 200
            from models import BillingEvent
            from utils.billing_guard import billing_period_end_for, record_billing_event

            if BillingEvent.query.filter_by(idempotency_key=f"stripe_invoice:{invoice_id}").first():
                return jsonify({"received": True, "duplicate": True}), 200

            billing_reason = (inv.get("billing_reason") or "").lower()
            if billing_reason == "subscription_create":
                return jsonify({"received": True, "skipped": "subscription_create"}), 200

            subscription_id = inv.get("subscription")
            customer_id = inv.get("customer")
            tenant = None
            if subscription_id:
                tenant = Tenant.query.filter_by(stripe_subscription_id=subscription_id).first()
            if not tenant and customer_id:
                tenant = Tenant.query.filter_by(stripe_customer_id=customer_id).first()
            if tenant:
                billing_cycle = (tenant.billing_cycle or "monthly").lower()
                now = datetime.utcnow()
                period_end = billing_period_end_for(now, billing_cycle)
                tenant.billing_period_start = now
                tenant.billing_period_end = period_end
                if (tenant.status or "").lower() == "past_due":
                    tenant.status = "active"
                record_billing_event(
                    tenant=tenant,
                    plan_id=(tenant.plan or "starter").lower(),
                    billing_cycle=billing_cycle,
                    source="stripe_invoice",
                    status="applied",
                    idempotency_key=f"stripe_invoice:{invoice_id}",
                    stripe_event_id=event_id or None,
                    stripe_subscription_id=subscription_id,
                    amount_cents=inv.get("amount_paid"),
                    billing_period_start=now,
                    billing_period_end=period_end,
                    details="Subscription renewal invoice",
                )
                db.session.commit()
                log_event("STRIPE_INVOICE_RENEWAL", details=f"tenant={tenant.id} invoice={invoice_id}")
                if inc_stripe_webhook:
                    inc_stripe_webhook(event_type, "renewed")
    except Exception as exc:
        logger.exception("Stripe webhook handler error: %s", exc)
        db.session.rollback()
        if inc_stripe_webhook:
            inc_stripe_webhook(event_type, "failed")
        return jsonify({"error": "handler failed"}), 500

    return jsonify({"received": True}), 200
