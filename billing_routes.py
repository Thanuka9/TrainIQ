"""Admin billing — plan selection and upgrades."""
from __future__ import annotations

import logging
from functools import wraps

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from audit import log_event
from extensions import db
from models import Tenant
from utils.billing_plans import (
    SALES_EMAIL,
    UPGRADEABLE_PLAN_IDS,
    apply_paid_plan,
    get_plan,
    get_public_plans,
    tenant_usage,
)
from utils.tenant_utils import user_tenant_id

billing_routes = Blueprint("billing_routes", __name__)
logger = logging.getLogger(__name__)


def super_admin_required(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        from admin_routes import _effective_super_admin
        if not _effective_super_admin():
            flash("Only Super Admins can manage billing.", "error")
            return redirect(url_for("general_routes.dashboard"))
        return func(*args, **kwargs)
    return wrapper


def _current_tenant() -> Tenant | None:
    tid = user_tenant_id()
    return Tenant.query.get(tid) if tid else None


@billing_routes.route("/admin/billing")
@login_required
@super_admin_required
def billing_home():
    tenant = _current_tenant()
    if not tenant:
        flash("No organization context.", "error")
        return redirect(url_for("general_routes.dashboard"))

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
    )


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

    ok, msg = apply_paid_plan(tenant, plan_id, billing_cycle=billing_cycle)
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
