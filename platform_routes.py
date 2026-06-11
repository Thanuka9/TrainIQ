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
from utils.tenant_utils import is_trainiq_staff, set_active_tenant_session

platform_routes = Blueprint("platform_routes", __name__)
logger = logging.getLogger(__name__)


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


@platform_routes.route("/platform/tenants")
@login_required
@platform_staff_required
def list_tenants():
    from utils.billing_plans import PLANS
    tenants = Tenant.query.order_by(Tenant.created_at.desc()).all()
    rows = []
    for t in tenants:
        stats = _tenant_stats(t.id)
        rows.append({"tenant": t, **stats})
    return render_template("admin_platform_tenants.html", tenants=rows, plan_catalog=PLANS)


@platform_routes.route("/platform/tenants/<int:tenant_id>/enter", methods=["POST"])
@login_required
@platform_staff_required
def enter_tenant(tenant_id):
    tenant = Tenant.query.get_or_404(tenant_id)
    set_active_tenant_session(tenant, platform_support=True)
    session["is_super_admin"] = True
    flash(f"Support mode: now viewing {tenant.name}.", "success")
    return redirect(url_for("admin_routes.admin_dashboard"))


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
    return redirect(url_for("platform_routes.list_tenants"))


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
    return redirect(url_for("platform_routes.list_tenants"))


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
            return redirect(url_for("platform_routes.list_tenants"))
    else:
        tenant.plan = plan_id
    tenant.status = (request.form.get("status") or tenant.status).strip()
    if plan_id == "trial" or plan_id not in PLANS:
        try:
            tenant.max_users = max(1, int(request.form.get("max_users") or tenant.max_users))
            tenant.max_storage_mb = max(100, int(request.form.get("max_storage_mb") or tenant.max_storage_mb))
        except ValueError:
            flash("Invalid numeric limits.", "error")
            return redirect(url_for("platform_routes.list_tenants"))
    tenant.billing_email = (request.form.get("billing_email") or "").strip() or tenant.billing_email
    db.session.commit()
    flash(f"Updated plan for '{tenant.name}'.", "success")
    return redirect(url_for("platform_routes.list_tenants"))
