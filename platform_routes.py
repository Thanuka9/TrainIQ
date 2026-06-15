"""TrainIQ platform operator routes — cross-tenant management for @trainiq.com staff."""
from __future__ import annotations

import logging
from datetime import datetime
from functools import wraps

from flask import Blueprint, flash, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required

from extensions import db
from models import Tenant, User, Exam, StudyMaterial, Task
from utils.billing_guard import apply_plan_upgrade
from utils.billing_plans import PLANS, apply_trial_to_tenant
from utils.platform_analytics import (
    filter_tenant_rows,
    get_platform_activity_feed,
    get_platform_analytics,
    get_platform_chart_series,
    get_platform_security_feed,
    get_platform_support_queue,
    get_revenue_analytics,
    get_tenant_detail,
    search_platform_users,
)
from utils.tenant_utils import is_trainiq_staff, is_platform_ceo, normalize_office_key, set_active_tenant_session

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


def platform_ceo_required(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated or not is_platform_ceo():
            flash("Platform CEO access only.", "error")
            return redirect(url_for("platform_routes.platform_staff"))
        return func(*args, **kwargs)
    return wrapper


def platform_permission_required(*permissions: str):
    """Require at least one platform staff permission (CEO always allowed)."""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            from utils.platform_staff_permissions import staff_has_permission

            if not current_user.is_authenticated or not is_trainiq_staff():
                flash("TrainIQ platform access only.", "error")
                return redirect(url_for("general_routes.dashboard"))
            if not any(staff_has_permission(current_user, p) for p in permissions):
                flash("Your staff role does not include access to this section.", "error")
                return redirect(url_for("platform_routes.platform_staff"))
            return func(*args, **kwargs)
        return wrapper
    return decorator


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


@platform_routes.route("/platform/staff")
@login_required
@platform_permission_required("staff.view")
def platform_staff():
    from utils.platform_staff import list_pending_staff_invites, list_platform_staff
    from utils.platform_staff_permissions import get_role_catalog

    staff = list_platform_staff()
    invites = list_pending_staff_invites()
    return render_template(
        "admin_platform_staff.html",
        staff=staff,
        invites=invites,
        role_catalog=get_role_catalog(),
        active_platform="staff",
        is_ceo=is_platform_ceo(),
    )


@platform_routes.route("/platform/staff/invite", methods=["POST"])
@login_required
@platform_ceo_required
def platform_staff_invite():
    from utils.platform_staff import (
        STAFF_ROLES,
        create_staff_invite,
        find_user_by_email,
        send_staff_invite_email,
    )
    from extensions import mail

    email = (request.form.get("email") or "").strip().lower()
    first_name = (request.form.get("first_name") or "").strip()
    last_name = (request.form.get("last_name") or "").strip()
    role = (request.form.get("role") or "support").strip().lower()

    if not all([email, first_name, last_name]):
        flash("Email, first name, and last name are required.", "error")
        return redirect(url_for("platform_routes.platform_staff"))

    if role not in STAFF_ROLES:
        flash("Invalid staff role.", "error")
        return redirect(url_for("platform_routes.platform_staff"))

    existing = find_user_by_email(email)
    if existing and getattr(existing, "is_platform_staff", False):
        flash("This user is already platform staff.", "error")
        return redirect(url_for("platform_routes.platform_staff"))

    invite = create_staff_invite(
        email=email,
        first_name=first_name,
        last_name=last_name,
        role=role,
        invited_by_user_id=current_user.id,
    )
    try:
        send_staff_invite_email(invite, mail)
        flash(f"Staff invite sent to {email}.", "success")
    except Exception as exc:
        logger.error("Platform staff invite email failed: %s", exc)
        flash("Invite created but email could not be sent.", "warning")

    return redirect(url_for("platform_routes.platform_staff"))


@platform_routes.route("/platform/staff/<int:staff_id>/role", methods=["POST"])
@login_required
@platform_ceo_required
def platform_staff_update_role(staff_id: int):
    from utils.platform_ceo import PLATFORM_CEO_EMAIL
    from utils.platform_staff import STAFF_ROLES

    user = User.query.get_or_404(staff_id)
    if (user.employee_email or "").lower().strip() == PLATFORM_CEO_EMAIL:
        flash("Cannot change the platform CEO role.", "error")
        return redirect(url_for("platform_routes.platform_staff"))

    role = (request.form.get("role") or "").strip().lower()
    if role not in STAFF_ROLES:
        flash("Invalid staff role.", "error")
        return redirect(url_for("platform_routes.platform_staff"))

    user.is_platform_staff = True
    user.platform_staff_role = role
    db.session.commit()
    flash(f"Updated {user.employee_email} to {role.title()} role.", "success")
    return redirect(url_for("platform_routes.platform_staff"))


@platform_routes.route("/platform/staff/<int:staff_id>/deactivate", methods=["POST"])
@login_required
@platform_ceo_required
def platform_staff_deactivate(staff_id: int):
    from utils.platform_ceo import PLATFORM_CEO_EMAIL

    user = User.query.get_or_404(staff_id)
    if (user.employee_email or "").lower().strip() == PLATFORM_CEO_EMAIL:
        flash("Cannot deactivate the platform CEO.", "error")
        return redirect(url_for("platform_routes.platform_staff"))

    user.is_platform_staff = False
    user.platform_staff_role = None
    db.session.commit()
    flash(f"Deactivated platform staff access for {user.employee_email}.", "success")
    return redirect(url_for("platform_routes.platform_staff"))


@platform_routes.route("/platform/staff/invites/<int:invite_id>/revoke", methods=["POST"])
@login_required
@platform_ceo_required
def platform_staff_invite_revoke(invite_id: int):
    from utils.platform_staff import revoke_staff_invite

    if revoke_staff_invite(invite_id):
        flash("Staff invite revoked.", "success")
    else:
        flash("Invite not found or already used.", "error")
    return redirect(url_for("platform_routes.platform_staff"))


@platform_routes.route("/platform")
@platform_routes.route("/platform/dashboard")
@login_required
@platform_permission_required("dashboard.view")
def platform_dashboard():
    stats = get_platform_analytics()
    q = (request.args.get("q") or "").strip()
    plan = (request.args.get("plan") or "").strip()
    status = (request.args.get("status") or "").strip()
    sort = (request.args.get("sort") or "users_desc").strip()
    filtered_rows = filter_tenant_rows(stats["tenant_rows"], q=q, plan=plan, status=status, sort=sort)
    charts = get_platform_chart_series(stats)
    return render_template(
        "admin_platform_dashboard.html",
        stats=stats,
        filtered_rows=filtered_rows,
        charts=charts,
        q=q,
        plan=plan,
        status=status,
        sort=sort,
        plan_catalog=PLANS,
        active_platform="dashboard",
    )


@platform_routes.route("/platform/activity")
@login_required
@platform_permission_required("activity.view")
def platform_activity():
    from datetime import datetime as dt

    start_raw = (request.args.get("start") or "").strip()
    end_raw = (request.args.get("end") or "").strip()
    start = end = None
    try:
        if start_raw:
            start = dt.strptime(start_raw, "%Y-%m-%d")
        if end_raw:
            end = dt.strptime(end_raw, "%Y-%m-%d").replace(hour=23, minute=59, second=59)
    except ValueError:
        flash("Invalid date filter — use YYYY-MM-DD.", "warning")

    feed = get_platform_activity_feed(limit=200, start=start, end=end)
    return render_template(
        "admin_platform_activity.html",
        feed=feed,
        active_platform="activity",
        start=start_raw,
        end=end_raw,
    )


@platform_routes.route("/platform/revenue")
@login_required
@platform_permission_required("revenue.view")
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
@platform_permission_required("users.view")
def platform_users():
    q = (request.args.get("q") or "").strip()
    tenant_id = request.args.get("tenant_id", type=int)
    status = (request.args.get("status") or "").strip()
    limit = min(request.args.get("limit", default=200, type=int) or 200, 1000)
    tenants = Tenant.query.order_by(Tenant.name).all()
    rows, total_matches = search_platform_users(q=q, tenant_id=tenant_id, status=status, limit=limit)
    return render_template(
        "admin_platform_users.html",
        rows=rows,
        total_matches=total_matches,
        shown_limit=limit,
        tenants=tenants,
        q=q,
        tenant_id=tenant_id,
        status=status,
        active_platform="users",
    )


@platform_routes.route("/platform/export/tenants.csv")
@login_required
@platform_permission_required("exports.data")
def export_tenants_csv():
    import csv
    import io

    from flask import Response

    stats = get_platform_analytics()
    rows = filter_tenant_rows(
        stats["tenant_rows"],
        q=(request.args.get("q") or "").strip(),
        plan=(request.args.get("plan") or "").strip(),
        status=(request.args.get("status") or "").strip(),
        sort=(request.args.get("sort") or "users_desc").strip(),
    )
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([
        "ID", "Organization", "Office Key", "Domain", "Plan", "Status",
        "Billing Email", "Users", "Max Users", "Courses", "Exams", "Tasks",
        "MRR", "Created", "Trial Ends",
    ])
    for row in rows:
        t = row["tenant"]
        writer.writerow([
            t.id, t.name, t.office_key or "", t.allowed_domain or "",
            t.plan or "", t.status or "", t.billing_email or "",
            row["users"], t.max_users or "", row["courses"], row["exams"],
            row["tasks"], row["mrr"],
            t.created_at.strftime("%Y-%m-%d") if t.created_at else "",
            t.trial_ends_at.strftime("%Y-%m-%d") if t.trial_ends_at else "",
        ])
    return Response(
        buf.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=trainiq_organizations.csv"},
    )


@platform_routes.route("/platform/export/users.csv")
@login_required
@platform_permission_required("exports.data")
def export_users_csv():
    import csv
    import io

    from flask import Response

    rows, _total = search_platform_users(
        q=(request.args.get("q") or "").strip(),
        tenant_id=request.args.get("tenant_id", type=int),
        status=(request.args.get("status") or "").strip(),
        limit=0,
    )
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([
        "ID", "First Name", "Last Name", "Email", "Employee ID",
        "Organization", "Office Key", "Verified", "Locked", "Super Admin", "Joined",
    ])
    for row in rows:
        u, t = row["user"], row["tenant"]
        writer.writerow([
            u.id, u.first_name, u.last_name, u.employee_email, u.employee_id or "",
            t.name if t else "", t.office_key if t else "",
            "yes" if u.is_verified else "no",
            "yes" if u.is_locked else "no",
            "yes" if u.is_super_admin else "no",
            u.join_date.strftime("%Y-%m-%d") if u.join_date else "",
        ])
    return Response(
        buf.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=trainiq_users.csv"},
    )


@platform_routes.route("/platform/support")
@login_required
@platform_permission_required("support.view")
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
@platform_permission_required("security.view")
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
@platform_permission_required("tenants.enter")
def exit_tenant():
    """Leave customer support mode and return to platform overview."""
    from audit import log_event

    home = Tenant.query.get(current_user.tenant_id)
    prev_name = session.get("tenant_name")
    session.pop("platform_support", None)
    session["is_super_admin"] = bool(current_user.is_super_admin)
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
@platform_permission_required("tenants.enter")
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
@platform_permission_required("tenants.view")
def list_tenants():
    stats = get_platform_analytics()
    q = (request.args.get("q") or "").strip()
    plan = (request.args.get("plan") or "").strip()
    status = (request.args.get("status") or "").strip()
    sort = (request.args.get("sort") or "users_desc").strip()
    rows = filter_tenant_rows(stats["tenant_rows"], q=q, plan=plan, status=status, sort=sort)
    return render_template(
        "admin_platform_tenants.html",
        tenants=rows,
        stats=stats,
        q=q,
        plan=plan,
        status=status,
        sort=sort,
        plan_catalog=PLANS,
        active_platform="tenants",
    )


@platform_routes.route("/platform/tenants/<int:tenant_id>")
@login_required
@platform_permission_required("tenants.view")
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
@platform_permission_required("tenants.enter")
def enter_tenant(tenant_id):
    tenant = Tenant.query.get_or_404(tenant_id)
    target = (request.form.get("target") or "admin").strip()
    return _enter_tenant(tenant, redirect_to=target)


@platform_routes.route("/platform/tenants/<int:tenant_id>/suspend", methods=["POST"])
@login_required
@platform_permission_required("tenants.manage")
def suspend_tenant(tenant_id):
    from audit import log_event

    tenant = Tenant.query.get_or_404(tenant_id)
    reason = (request.form.get("reason") or "Suspended by TrainIQ support.").strip()
    tenant.status = "suspended"
    tenant.suspended_at = datetime.utcnow()
    tenant.suspended_reason = reason
    db.session.commit()
    log_event(
        "PLATFORM_SUSPEND_TENANT",
        user=current_user,
        target=tenant,
        tenant_id=tenant.id,
        reason=reason,
    )
    flash(f"Tenant '{tenant.name}' suspended.", "warning")
    return redirect(request.referrer or url_for("platform_routes.list_tenants"))


@platform_routes.route("/platform/tenants/<int:tenant_id>/activate", methods=["POST"])
@login_required
@platform_permission_required("tenants.manage")
def activate_tenant(tenant_id):
    from audit import log_event

    tenant = Tenant.query.get_or_404(tenant_id)
    tenant.status = "active"
    tenant.suspended_at = None
    tenant.suspended_reason = None
    db.session.commit()
    log_event(
        "PLATFORM_ACTIVATE_TENANT",
        user=current_user,
        target=tenant,
        tenant_id=tenant.id,
    )
    flash(f"Tenant '{tenant.name}' reactivated.", "success")
    return redirect(request.referrer or url_for("platform_routes.list_tenants"))


@platform_routes.route("/platform/tenants/<int:tenant_id>/update", methods=["POST"])
@login_required
@platform_permission_required("tenants.manage")
def update_tenant_plan(tenant_id):
    from audit import log_event

    tenant = Tenant.query.get_or_404(tenant_id)
    plan_id = (request.form.get("plan") or tenant.plan).strip().lower()
    prev_plan = tenant.plan
    prev_status = tenant.status
    if plan_id == "trial":
        apply_trial_to_tenant(tenant)
    elif plan_id in PLANS and plan_id != "trial":
        ok, msg = apply_plan_upgrade(tenant, plan_id, source="platform_override", force=True)
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
    custom_mrr_raw = (request.form.get("custom_mrr_cents") or "").strip()
    if custom_mrr_raw.isdigit():
        tenant.custom_mrr_cents = int(custom_mrr_raw)
    elif custom_mrr_raw == "":
        tenant.custom_mrr_cents = None
    db.session.commit()
    log_event(
        "PLATFORM_UPDATE_TENANT",
        user=current_user,
        target=tenant,
        tenant_id=tenant.id,
        previous_plan=prev_plan,
        previous_status=prev_status,
        plan=tenant.plan,
        status=tenant.status,
    )
    flash(f"Updated plan for '{tenant.name}'.", "success")
    return redirect(request.referrer or url_for("platform_routes.tenant_detail", tenant_id=tenant_id))


def _send_user_verification_email(user: User) -> bool:
    """Resend email verification link to a user."""
    from auth_routes import s
    from extensions import mail
    from flask import render_template as rt
    from flask_mail import Message

    if user.is_verified:
        return False
    token = s.dumps(user.employee_email, salt='email-confirmation')
    user.verification_token = token
    db.session.commit()
    verify_url = url_for('auth_routes.verify_email', token=token, _external=True)
    msg = Message(subject="Verify Your Email", recipients=[user.employee_email])
    msg.body = f"Please verify your email by clicking the link:\n\n{verify_url}"
    msg.html = rt('emails/verification_email.html', user=user, verify_url=verify_url)
    try:
        mail.send(msg)
        return True
    except Exception as exc:
        logger.error("Platform resend verification failed: %s", exc)
        return False


@platform_routes.route("/platform/users/<int:user_id>/unlock-level", methods=["POST"])
@login_required
@platform_permission_required("users.actions")
def platform_unlock_user_level(user_id):
    from audit import log_event

    user = User.query.get_or_404(user_id)
    try:
        level = max(1, int(request.form.get("level") or user.get_current_level() or 1))
    except ValueError:
        flash("Invalid level.", "error")
        return redirect(request.referrer or url_for("platform_routes.platform_users"))

    prev = user.get_current_level()
    user.current_level = level
    db.session.commit()
    log_event(
        "PLATFORM_UNLOCK_LEVEL",
        user=current_user,
        target=user,
        previous_level=prev,
        new_level=level,
    )
    flash(f"Set {user.first_name}'s level to {level}.", "success")
    return redirect(request.referrer or url_for("platform_routes.platform_users"))


@platform_routes.route("/platform/users/<int:user_id>/resend-verification", methods=["POST"])
@login_required
@platform_permission_required("users.actions")
def platform_resend_verification(user_id):
    from audit import log_event

    user = User.query.get_or_404(user_id)
    if user.is_verified:
        flash("User is already verified.", "info")
    elif _send_user_verification_email(user):
        log_event("PLATFORM_RESEND_VERIFICATION", user=current_user, target=user)
        flash(f"Verification email sent to {user.employee_email}.", "success")
    else:
        flash("Could not send verification email.", "error")
    return redirect(request.referrer or url_for("platform_routes.platform_users"))


@platform_routes.route("/platform/users/<int:user_id>/force-password-reset", methods=["POST"])
@login_required
@platform_permission_required("users.actions")
def platform_force_password_reset(user_id):
    """Generate a password reset token and email the user (platform admin action)."""
    from datetime import timedelta

    from auth_routes import s
    from extensions import mail
    from flask_mail import Message
    from models import PasswordResetRequest
    from audit import log_event

    user = User.query.get_or_404(user_id)
    token = s.dumps(user.employee_email, salt="password-reset-salt")
    expires_at = datetime.utcnow() + timedelta(hours=1)

    pr = PasswordResetRequest(
        user_id=user.id,
        token=token,
        expires_at=expires_at,
    )
    db.session.add(pr)
    user.password_reset_token = token
    user.password_reset_expiration = expires_at
    db.session.commit()

    reset_url = url_for("auth_routes.reset_password", token=token, _external=True)
    msg = Message(subject="Password Reset", recipients=[user.employee_email])
    msg.body = f"Reset your password using this link: {reset_url}"
    msg.html = render_template(
        "emails/password_reset_email.html",
        user=user,
        reset_url=reset_url,
    )
    try:
        mail.send(msg)
        log_event("PLATFORM_FORCE_PASSWORD_RESET", user=current_user, target=user)
        flash(f"Password reset email sent to {user.employee_email}.", "success")
    except Exception as exc:
        logger.error("Platform force password reset failed: %s", exc)
        flash("Could not send password reset email.", "error")

    return redirect(request.referrer or url_for("platform_routes.platform_users"))


@platform_routes.route("/platform/export/activity.csv")
@login_required
@platform_permission_required("activity.export")
def export_activity_csv():
    import csv
    import io

    from flask import Response

    start_raw = (request.args.get("start") or "").strip()
    end_raw = (request.args.get("end") or "").strip()
    start = end = None
    try:
        if start_raw:
            start = datetime.strptime(start_raw, "%Y-%m-%d")
        if end_raw:
            end = datetime.strptime(end_raw, "%Y-%m-%d").replace(hour=23, minute=59, second=59)
    except ValueError:
        pass

    feed = get_platform_activity_feed(limit=5000, start=start, end=end)
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["Time", "Event", "Summary", "Actor", "IP"])
    for row in feed:
        ev = row["event"]
        actor = row.get("actor")
        writer.writerow([
            ev.created_at.strftime("%Y-%m-%d %H:%M:%S") if ev.created_at else "",
            ev.event_type,
            row.get("summary") or "",
            actor.employee_email if actor else "",
            ev.ip_address or "",
        ])
    return Response(
        buf.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=trainiq_platform_activity.csv"},
    )
