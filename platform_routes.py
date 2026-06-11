"""TrainIQ platform operator routes — cross-tenant management for @trainiq.com staff."""
from __future__ import annotations

import logging
from datetime import datetime
from functools import wraps

from flask import Blueprint, flash, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required

from extensions import db
from models import Tenant, User, Exam, StudyMaterial, Task
from utils.billing_plans import PLANS, apply_paid_plan, apply_trial_to_tenant
from utils.platform_analytics import (
    get_platform_activity_feed,
    get_platform_analytics,
    get_platform_security_feed,
    get_platform_support_queue,
    get_revenue_analytics,
    get_tenant_detail,
    search_platform_users,
)
from utils.tenant_utils import is_trainiq_staff, normalize_office_key, set_active_tenant_session

platform_routes = Blueprint("platform_routes", __name__)
logger = logging.getLogger(__name__)

PLATFORM_ENDPOINTS = (
    "platform_routes.platform_dashboard",
    "platform_routes.list_tenants",
    "platform_routes.tenant_detail",
    "platform_routes.platform_users",
    "platform_routes.platform_support",
    "platform_routes.platform_security",
    "platform_routes.platform_revenue",
)


def platform_staff_required(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated or not is_trainiq_staff():
            flash("TrainIQ platform access only.", "error")
            return redirect(url_for("general_routes.dashboard"))
        return func(*args, **kwargs)
    return wrapper


def _tenant_stats(tenant_id: int) -> dict:
    return {
        "users": User.query.filter_by(tenant_id=tenant_id).count(),
        "exams": Exam.query.filter_by(tenant_id=tenant_id).count(),
        "courses": StudyMaterial.query.filter_by(tenant_id=tenant_id).count(),
        "tasks": Task.query.filter_by(tenant_id=tenant_id).count(),
    }


def _enter_tenant(tenant: Tenant, *, redirect_to: str = "admin_dashboard"):
    from audit import log_event

    set_active_tenant_session(tenant, platform_support=True)
    session["is_super_admin"] = True
    log_event(
        "PLATFORM_ENTER_TENANT",
        user=current_user,
        target=tenant,
        tenant_name=tenant.name,
        office_key=tenant.office_key,
        tenant_id=tenant.id,
    )
    flash(f"Support mode: now viewing {tenant.name} ({tenant.office_key or tenant.id}).", "success")
    if redirect_to == "users":
        return redirect(url_for("admin_routes.view_users"))
    if redirect_to == "support":
        return redirect(url_for("admin_routes.admin_list_tickets"))
    if redirect_to == "billing":
        return redirect(url_for("billing_routes.billing_home"))
    if redirect_to == "settings":
        return redirect(url_for("admin_routes.tenant_settings"))
    return redirect(url_for("admin_routes.admin_dashboard"))


@platform_routes.route("/platform")
@platform_routes.route("/platform/dashboard")
@login_required
@platform_staff_required
def platform_dashboard():
    stats = get_platform_analytics()
    return render_template(
        "admin_platform_dashboard.html",
        stats=stats,
        plan_catalog=PLANS,
        active_platform="dashboard",
    )


@platform_routes.route("/platform/activity")
@login_required
@platform_staff_required
def platform_activity():
    feed = get_platform_activity_feed(limit=150)
    return render_template(
        "admin_platform_activity.html",
        feed=feed,
        active_platform="activity",
    )


@platform_routes.route("/platform/revenue")
@login_required
@platform_staff_required
def platform_revenue():
    revenue = get_revenue_analytics()
    return render_template(
        "admin_platform_revenue.html",
        revenue=revenue,
        plan_catalog=PLANS,
        active_platform="revenue",
    )


@platform_routes.route("/platform/users")
@login_required
@platform_staff_required
def platform_users():
    q = (request.args.get("q") or "").strip()
    tenant_id = request.args.get("tenant_id", type=int)
    status = (request.args.get("status") or "").strip()
    tenants = Tenant.query.order_by(Tenant.name).all()
    rows = search_platform_users(q=q, tenant_id=tenant_id, status=status)
    return render_template(
        "admin_platform_users.html",
        rows=rows,
        tenants=tenants,
        q=q,
        tenant_id=tenant_id,
        status=status,
        active_platform="users",
    )


@platform_routes.route("/platform/support")
@login_required
@platform_staff_required
def platform_support():
    status = (request.args.get("status") or "open").strip()
    rows = get_platform_support_queue(status=status)
    return render_template(
        "admin_platform_support.html",
        rows=rows,
        status=status,
        active_platform="support",
    )


@platform_routes.route("/platform/security")
@login_required
@platform_staff_required
def platform_security():
    event_type = (request.args.get("event_type") or "").strip()
    feed = get_platform_security_feed(limit=150, event_type=event_type)
    return render_template(
        "admin_platform_security.html",
        feed=feed,
        event_type=event_type,
        active_platform="security",
    )


@platform_routes.route("/platform/exit", methods=["POST"])
@login_required
@platform_staff_required
def exit_tenant():
    """Leave customer support mode and return to platform overview."""
    from audit import log_event

    home = Tenant.query.get(current_user.tenant_id)
    prev_name = session.get("tenant_name")
    session.pop("platform_support", None)
    log_event(
        "PLATFORM_EXIT_TENANT",
        user=current_user,
        previous_tenant=prev_name,
    )
    if home:
        set_active_tenant_session(home, platform_support=False)
        flash(f"Exited support mode. Back to {home.name}.", "success")
    else:
        session.pop("tenant_id", None)
        session.pop("tenant_name", None)
        flash("Exited support mode.", "success")
    return redirect(url_for("platform_routes.platform_dashboard"))


@platform_routes.route("/platform/enter-by-key", methods=["POST"])
@login_required
@platform_staff_required
def enter_by_office_key():
    office_key = normalize_office_key(request.form.get("office_key"))
    target = (request.form.get("target") or "admin").strip()
    if not office_key:
        flash("Enter an Office Key.", "error")
        return redirect(url_for("platform_routes.platform_dashboard"))
    tenant = Tenant.query.filter_by(office_key=office_key).first()
    if not tenant:
        flash(f"No organization found for Office Key '{office_key}'.", "error")
        return redirect(url_for("platform_routes.platform_dashboard"))
    return _enter_tenant(tenant, redirect_to=target)


@platform_routes.route("/platform/tenants")
@login_required
@platform_staff_required
def list_tenants():
    tenants = Tenant.query.order_by(Tenant.created_at.desc()).all()
    rows = []
    for t in tenants:
        stats = _tenant_stats(t.id)
        rows.append({"tenant": t, **stats})
    return render_template(
        "admin_platform_tenants.html",
        tenants=rows,
        plan_catalog=PLANS,
        active_platform="tenants",
    )


@platform_routes.route("/platform/tenants/<int:tenant_id>")
@login_required
@platform_staff_required
def tenant_detail(tenant_id):
    detail = get_tenant_detail(tenant_id)
    if not detail:
        flash("Organization not found.", "error")
        return redirect(url_for("platform_routes.list_tenants"))
    return render_template(
        "admin_platform_tenant_detail.html",
        detail=detail,
        plan_catalog=PLANS,
        active_platform="tenants",
    )


@platform_routes.route("/platform/tenants/<int:tenant_id>/enter", methods=["POST"])
@login_required
@platform_staff_required
def enter_tenant(tenant_id):
    tenant = Tenant.query.get_or_404(tenant_id)
    target = (request.form.get("target") or "admin").strip()
    return _enter_tenant(tenant, redirect_to=target)


@platform_routes.route("/platform/tenants/<int:tenant_id>/suspend", methods=["POST"])
@login_required
@platform_staff_required
def suspend_tenant(tenant_id):
    tenant = Tenant.query.get_or_404(tenant_id)
    reason = (request.form.get("reason") or "Suspended by TrainIQ support.").strip()
    tenant.status = "suspended"
    tenant.suspended_at = datetime.utcnow()
    tenant.suspended_reason = reason
    db.session.commit()
    flash(f"Tenant '{tenant.name}' suspended.", "warning")
    return redirect(request.referrer or url_for("platform_routes.list_tenants"))


@platform_routes.route("/platform/tenants/<int:tenant_id>/activate", methods=["POST"])
@login_required
@platform_staff_required
def activate_tenant(tenant_id):
    tenant = Tenant.query.get_or_404(tenant_id)
    tenant.status = "active"
    tenant.suspended_at = None
    tenant.suspended_reason = None
    db.session.commit()
    flash(f"Tenant '{tenant.name}' reactivated.", "success")
    return redirect(request.referrer or url_for("platform_routes.list_tenants"))


@platform_routes.route("/platform/tenants/<int:tenant_id>/update", methods=["POST"])
@login_required
@platform_staff_required
def update_tenant_plan(tenant_id):
    tenant = Tenant.query.get_or_404(tenant_id)
    plan_id = (request.form.get("plan") or tenant.plan).strip().lower()
    if plan_id == "trial":
        apply_trial_to_tenant(tenant)
    elif plan_id in PLANS and plan_id != "trial":
        ok, msg = apply_paid_plan(tenant, plan_id)
        if not ok:
            flash(msg, "error")
            return redirect(request.referrer or url_for("platform_routes.list_tenants"))
    else:
        tenant.plan = plan_id
    tenant.status = (request.form.get("status") or tenant.status).strip()
    if plan_id == "trial" or plan_id not in PLANS:
        try:
            tenant.max_users = max(1, int(request.form.get("max_users") or tenant.max_users))
            tenant.max_storage_mb = max(100, int(request.form.get("max_storage_mb") or tenant.max_storage_mb))
        except ValueError:
            flash("Invalid numeric limits.", "error")
            return redirect(request.referrer or url_for("platform_routes.list_tenants"))
    tenant.billing_email = (request.form.get("billing_email") or "").strip() or tenant.billing_email
    db.session.commit()
    flash(f"Updated plan for '{tenant.name}'.", "success")
    return redirect(request.referrer or url_for("platform_routes.tenant_detail", tenant_id=tenant_id))
