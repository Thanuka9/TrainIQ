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

# CEO may manually trigger only these background jobs from Operations.
PLATFORM_SCHEDULER_MANUAL_JOBS = frozenset({
    "db_performance_monitor",
    "platform_ops_agents",
})


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
    from utils.tenant_limits import tenant_is_active
    from utils.tenant_utils import is_platform_tenant

    if is_platform_tenant(tenant):
        flash("Cannot enter support mode for the TrainIQ platform organization.", "error")
        return redirect(url_for("platform_routes.platform_dashboard"))

    if not tenant_is_active(tenant):
        status = (getattr(tenant, "status", None) or "inactive").lower()
        flash(
            f"Support mode: entering {tenant.name} — organization is {status}. "
            "Customer access may be limited; changes are audited.",
            "warning",
        )

    set_active_tenant_session(tenant, platform_support=True)
    from utils.support_access import begin_support_session

    begin_support_session(write_elevated=False)
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
@platform_permission_required("staff.manage")
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
@platform_permission_required("staff.manage")
def platform_staff_update_role(staff_id: int):
    from utils.platform_staff import STAFF_ROLES, validate_staff_target

    user, err = validate_staff_target(staff_id)
    if not user:
        flash(err or "Invalid staff member.", "error")
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
@platform_permission_required("staff.manage")
def platform_staff_deactivate(staff_id: int):
    from utils.platform_staff import validate_staff_target

    user, err = validate_staff_target(staff_id)
    if not user:
        flash(err or "Invalid staff member.", "error")
        return redirect(url_for("platform_routes.platform_staff"))

    user.is_platform_staff = False
    user.platform_staff_role = None
    db.session.commit()
    flash(f"Deactivated platform staff access for {user.employee_email}.", "success")
    return redirect(url_for("platform_routes.platform_staff"))


@platform_routes.route("/platform/staff/invites/<int:invite_id>/revoke", methods=["POST"])
@login_required
@platform_permission_required("staff.manage")
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
    from utils.billing_history import monthly_revenue_series, recent_billing_events

    revenue = get_revenue_analytics()
    revenue['mrr_history'] = monthly_revenue_series(months=12)
    revenue['recent_billing_events'] = recent_billing_events(limit=20)
    return render_template(
        "admin_platform_revenue.html",
        revenue=revenue,
        plan_catalog=PLANS,
        active_platform="revenue",
    )


@platform_routes.route("/platform/revenue/reconcile", methods=["POST"])
@login_required
@platform_permission_required("revenue.view")
def platform_revenue_reconcile():
    from utils.billing_reconcile import reconcile_stripe_tenants
    from utils.ops_cache import invalidate_json_cached

    invalidate_json_cached("stripe_billing_reconcile")
    result = reconcile_stripe_tenants()
    if not result.get("available"):
        flash(result.get("message") or "Stripe reconcile unavailable.", "error")
    elif result.get("mismatch_count"):
        flash(
            f"Stripe reconcile found {result['mismatch_count']} issue(s) across {result['checked']} subscriptions.",
            "warning",
        )
    else:
        flash(f"Stripe reconcile OK — {result['checked']} subscription(s) checked.", "success")
    return redirect(url_for("platform_routes.platform_revenue"))


@platform_routes.route("/platform/tenants/<int:tenant_id>/export.json")
@login_required
@platform_permission_required("exports.data")
def export_tenant_json(tenant_id: int):
    from flask import jsonify
    from utils.tenant_export import build_tenant_export

    payload = build_tenant_export(tenant_id)
    if not payload:
        flash("Tenant not found.", "error")
        return redirect(url_for("platform_routes.list_tenants"))
    return jsonify(payload)


@platform_routes.route("/platform/export/access-review.csv")
@login_required
@platform_permission_required("security.view")
def export_access_review_csv():
    from flask import Response
    from utils.access_review_export import access_review_csv

    csv_data = access_review_csv()
    return Response(
        csv_data,
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=trainiq-access-review.csv"},
    )


@platform_routes.route("/platform/tenants/<int:tenant_id>/anonymize", methods=["POST"])
@login_required
@platform_permission_required("tenants.manage")
def anonymize_tenant_route(tenant_id: int):
    from audit import log_event
    from utils.tenant_gdpr import anonymize_tenant
    from utils.tenant_utils import is_platform_tenant

    tenant = Tenant.query.get_or_404(tenant_id)
    if is_platform_tenant(tenant):
        flash("Cannot anonymize the platform organization.", "error")
        return redirect(url_for("platform_routes.tenant_detail", tenant_id=tenant_id))

    confirm = (request.form.get("confirm_name") or "").strip()
    if confirm != tenant.name:
        flash("Confirmation failed — type the organization name exactly.", "error")
        return redirect(url_for("platform_routes.tenant_detail", tenant_id=tenant_id))

    ok, msg = anonymize_tenant(
        tenant,
        actor_user_id=current_user.id,
        purge_storage=request.form.get("purge_storage") == "1",
    )
    if ok:
        log_event("TENANT_GDPR_ANONYMIZE", user=current_user, target=tenant, tenant_id=tenant.id)
        flash(msg, "success")
        return redirect(url_for("platform_routes.list_tenants"))
    flash(msg, "error")
    return redirect(url_for("platform_routes.tenant_detail", tenant_id=tenant_id))


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


@platform_routes.route("/platform/security/totp", methods=["GET", "POST"])
@login_required
@platform_permission_required("security.view")
def platform_security_totp():
    """Enroll or disable TOTP authenticator for platform staff."""
    from extensions import db
    from utils.totp_2fa import (
        generate_totp_secret,
        provisioning_uri,
        totp_available,
        user_has_totp,
        verify_totp_code,
    )

    if not totp_available():
        flash("Authenticator app support is not installed on this server.", "error")
        return redirect(url_for("platform_routes.platform_security"))

    if request.method == "POST":
        action = (request.form.get("action") or "enable").strip().lower()
        if action == "disable":
            if not user_has_totp(current_user):
                flash("Authenticator is not enabled.", "info")
                return redirect(url_for("platform_routes.platform_security"))
            code = (request.form.get("totp_code") or "").strip()
            if not verify_totp_code(current_user.totp_secret, code):
                flash("Invalid code — could not disable authenticator.", "error")
                return redirect(url_for("platform_routes.platform_security_totp"))
            current_user.totp_secret = None
            current_user.totp_enabled = False
            db.session.commit()
            flash("Authenticator app disabled. Email 2FA will be used when required.", "success")
            return redirect(url_for("platform_routes.platform_security"))

        code = (request.form.get("totp_code") or "").strip()
        pending_secret = session.pop("pending_totp_secret", None)
        if not pending_secret or not verify_totp_code(pending_secret, code):
            flash("Invalid verification code. Scan the QR code and try again.", "error")
            return redirect(url_for("platform_routes.platform_security_totp"))
        current_user.totp_secret = pending_secret
        current_user.totp_enabled = True
        db.session.commit()
        flash("Authenticator app enabled for your account.", "success")
        return redirect(url_for("platform_routes.platform_security"))

    pending_secret = session.get("pending_totp_secret")
    if not user_has_totp(current_user) and not pending_secret:
        pending_secret = generate_totp_secret()
        session["pending_totp_secret"] = pending_secret

    qr_uri = provisioning_uri(
        secret=pending_secret or current_user.totp_secret or "",
        email=current_user.employee_email,
    )
    return render_template(
        "platform_totp_enroll.html",
        totp_enabled=user_has_totp(current_user),
        qr_uri=qr_uri,
        active_platform="security",
    )


@platform_routes.route("/platform/exit", methods=["POST"])
@login_required
@platform_permission_required("tenants.enter")
def exit_tenant():
    """Leave customer support mode and return to platform overview."""
    from audit import log_event
    from utils.tenant_db import load_tenant_by_id

    home = load_tenant_by_id(current_user.tenant_id, label='platform_exit_tenant')
    prev_name = session.get("tenant_name")
    session.pop("platform_support", None)
    from utils.support_access import clear_support_access

    clear_support_access()
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


@platform_routes.route("/platform/support/elevate-write", methods=["POST"])
@login_required
@platform_permission_required("tenants.enter")
def elevate_support_write():
    """Grant time-limited write access while in customer support mode."""
    from audit import log_event
    from utils.platform_staff_permissions import staff_has_permission
    from utils.support_access import (
        can_support_write,
        elevate_support_write_access,
        is_in_support_mode,
        log_support_action,
    )

    if not is_in_support_mode():
        flash("Not in support mode.", "error")
        return redirect(url_for("platform_routes.platform_dashboard"))

    if can_support_write():
        flash("Write access is already enabled for this support session.", "info")
        return redirect(request.referrer or url_for("admin_routes.admin_dashboard"))

    if not staff_has_permission(current_user, "tenants.manage"):
        log_support_action("elevate_write_denied", allowed=False)
        flash("Your role cannot enable write access in support mode.", "error")
        return redirect(request.referrer or url_for("admin_routes.admin_dashboard"))

    from models import Tenant

    tenant = Tenant.query.get(session.get("tenant_id"))
    confirm_key = (request.form.get("office_key_confirm") or "").strip().upper()
    expected = (getattr(tenant, "office_key", None) or "").strip().upper()
    if not expected or confirm_key != expected:
        log_support_action("elevate_write_denied", allowed=False, extra={"reason": "office_key_mismatch"})
        flash("Break-glass denied: type the customer Office Key exactly to enable write access.", "error")
        return redirect(request.referrer or url_for("admin_routes.admin_dashboard"))

    if not request.form.get("breakglass_ack"):
        flash("Confirm customer authorization before enabling write access.", "error")
        return redirect(request.referrer or url_for("admin_routes.admin_dashboard"))

    elevate_support_write_access()
    log_support_action("elevate_write", allowed=True)
    log_event(
        "PLATFORM_SUPPORT_WRITE_ELEVATE",
        user=current_user,
        tenant_id=session.get("tenant_id"),
        tenant_name=session.get("tenant_name"),
    )
    flash(
        "Write access enabled for this support session (time-limited). Changes are audited.",
        "warning",
    )
    return redirect(request.referrer or url_for("admin_routes.admin_dashboard"))


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
    from utils.tenant_utils import is_platform_tenant

    tenant = Tenant.query.get_or_404(tenant_id)
    if is_platform_tenant(tenant):
        flash("Cannot suspend the TrainIQ platform organization.", "error")
        return redirect(request.referrer or url_for("platform_routes.list_tenants"))

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
    from utils.tenant_utils import is_platform_tenant

    tenant = Tenant.query.get_or_404(tenant_id)
    if is_platform_tenant(tenant):
        flash("Cannot modify the TrainIQ platform organization.", "error")
        return redirect(request.referrer or url_for("platform_routes.list_tenants"))

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
    from utils.tenant_utils import is_platform_tenant

    tenant = Tenant.query.get_or_404(tenant_id)
    if is_platform_tenant(tenant):
        flash("Cannot modify the TrainIQ platform organization.", "error")
        return redirect(request.referrer or url_for("platform_routes.list_tenants"))

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
    from utils.tenant_db import invalidate_request_tenant_cache

    invalidate_request_tenant_cache(tenant.id)
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


def _restart_configured() -> bool:
    import os
    if (os.getenv("PLATFORM_RESTART_WEBHOOK_URL") or "").strip():
        return True
    site = (os.getenv("WEBSITE_SITE_NAME") or os.getenv("AZURE_WEBAPP_NAME") or "").strip()
    user = (os.getenv("AZURE_WEBSITE_PUBLISH_USER") or "").strip()
    password = (os.getenv("AZURE_WEBSITE_PUBLISH_PASSWORD") or "").strip()
    return bool(site and user and password)


@platform_routes.route("/platform/operations")
@login_required
@platform_permission_required("operations.view")
def platform_operations():
    """CEO Platform Operations — Postgres, MongoDB, AI, integrations (no manual coding)."""
    import os
    import sys
    import platform

    from utils.platform_ops import get_platform_ops_status_for_tab

    tab = request.args.get("tab", "overview")
    ops = get_platform_ops_status_for_tab(tab, cache_seconds=30)
    page = ops['postgres'].get('page') or {}

    # Fetch Audit logs if tab is 'audit'
    audit_logs = []
    if tab == "audit":
        try:
            audit_logs = get_platform_activity_feed(limit=50)
        except Exception as exc:
            logger.error("Failed to retrieve audit logs: %s", exc)

    # Fetch Scheduler jobs if tab is 'system'
    scheduler_jobs = []
    if tab == "system":
        from extensions import scheduler
        try:
            for job in scheduler.get_jobs():
                trigger_str = str(job.trigger)
                next_run = job.next_run_time.strftime("%Y-%m-%d %H:%M:%S") if job.next_run_time else "Paused/None"
                scheduler_jobs.append({
                    "id": job.id,
                    "next_run": next_run,
                    "trigger": trigger_str,
                    "pending": job.pending,
                })
        except Exception as exc:
            logger.warning("Failed to retrieve scheduler jobs: %s", exc)

    # Fetch System metrics if tab is 'system'
    system_info = {}
    if tab == "system":
        try:
            import psutil
            cpu_percent = psutil.cpu_percent()
            mem = psutil.virtual_memory()
            mem_percent = mem.percent
            mem_used = int(mem.used / (1024 * 1024))
            mem_total = int(mem.total / (1024 * 1024))
            disk = psutil.disk_usage("/")
            disk_percent = disk.percent
            disk_used = int(disk.used / (1024 * 1024 * 1024))
            disk_total = int(disk.total / (1024 * 1024 * 1024))
        except ImportError:
            cpu_percent = None
            mem_percent = None
            mem_used = None
            mem_total = None
            disk_percent = None
            disk_used = None
            disk_total = None

        system_info = {
            "python_version": sys.version.split()[0],
            "platform": platform.platform(),
            "cpu_percent": cpu_percent,
            "mem_percent": mem_percent,
            "mem_used": mem_used,
            "mem_total": mem_total,
            "disk_percent": disk_percent,
            "disk_used": disk_used,
            "disk_total": disk_total,
        }

    from utils.ops_agents import load_all_agent_reports, run_ops_agent, VALID_DOMAINS
    from utils.platform_ops_runs import latest_ops_runs
    from utils.db_metric_samples import ops_trend_bundle
    from utils.maintenance_window import is_peak_traffic_window

    ops_agents = load_all_agent_reports()
    agent_tab = tab if tab in VALID_DOMAINS else 'overview'
    if agent_tab not in ops_agents:
        try:
            ops_agents[agent_tab] = run_ops_agent(agent_tab, force=False, use_ai=False)
        except Exception as exc:
            logger.warning("Ops agent bootstrap failed for %s: %s", agent_tab, exc)

    return render_template(
        "admin_platform_operations.html",
        ops=ops,
        snapshot=page.get("snapshot"),
        summary=page.get("summary", {}),
        recommendations=page.get("recommendations", []),
        postgres_stats=page.get("postgres_stats", {}),
        mongo_stats=page.get("mongo_stats", {}),
        history=page.get("history", []),
        tables_ready=page.get("tables_ready", False),
        migration_status=ops["postgres"]["migration"],
        last_maintenance=ops["postgres"]["last_maintenance"],
        mongo=ops["mongo"],
        ai=ops["ai"],
        integrations=ops["integrations"],
        active_tab=tab,
        auto_apply_enabled=os.getenv("DB_OPTIMIZER_AUTO_APPLY", "").lower() in ("1", "true", "yes"),
        monitor_interval_hours=max(1, int(os.getenv("DB_MONITOR_INTERVAL_HOURS", "6"))),
        restart_configured=_restart_configured(),
        active_platform="operations",
        audit_logs=audit_logs,
        scheduler_jobs=scheduler_jobs,
        system_info=system_info,
        ops_agents=ops_agents,
        recent_ops_runs=latest_ops_runs(limit=15),
        metric_trends=ops_trend_bundle(limit=24) if tab == 'postgres' else None,
        peak_hours_warning=is_peak_traffic_window(),
    )


@platform_routes.route("/platform/db-health")
@login_required
@platform_permission_required("operations.view")
def platform_db_health_legacy_redirect():
    """Legacy URL — redirect to canonical Operations Console."""
    tab = request.args.get("tab", "postgres")
    return redirect(url_for("platform_routes.platform_operations", tab=tab))


@platform_routes.route("/platform/operations/run", methods=["POST"])
@platform_routes.route("/platform/db-health/run", methods=["POST"])
@login_required
@platform_permission_required("operations.view")
def platform_operations_run():
    from utils.platform_ops_orchestrator import queue_or_run_health_cycle

    try:
        result = queue_or_run_health_cycle(
            source='ceo_scan',
            apply_safe=False,
            blocking_lock=True,
            actor_user_id=current_user.id,
        )
        if result.get('queued'):
            flash('DB monitor scan queued on the ops worker.', 'success')
        else:
            monitor = result.get('monitor') or {}
            flash(
                f"DB monitor cycle complete — status {monitor.get('status', result.get('status'))}, "
                f"{monitor.get('issue_count', 0)} issue(s).",
                "success",
            )
    except Exception as exc:
        logger.error("Manual DB monitor run failed: %s", exc, exc_info=True)
        flash("DB monitor cycle failed. Check server logs.", "error")
    return redirect(url_for("platform_routes.platform_operations"))


@platform_routes.route("/platform/operations/apply/<int:rec_id>", methods=["POST"])
@platform_routes.route("/platform/db-health/apply/<int:rec_id>", methods=["POST"])
@login_required
@platform_permission_required("operations.view")
def platform_operations_apply(rec_id: int):
    from utils.db_optimizer_agent import apply_recommendation

    ok, message = apply_recommendation(rec_id, actor_user_id=current_user.id)
    flash(message, "success" if ok else "error")
    return redirect(url_for("platform_routes.platform_operations"))


@platform_routes.route("/platform/operations/apply-safe", methods=["POST"])
@platform_routes.route("/platform/db-health/apply-safe", methods=["POST"])
@login_required
@platform_permission_required("operations.view")
def platform_operations_apply_safe():
    from utils.platform_ops_orchestrator import queue_or_run_health_cycle

    result = queue_or_run_health_cycle(
        source='ceo_apply',
        apply_safe=True,
        blocking_lock=True,
        actor_user_id=current_user.id,
    )
    if result.get('queued'):
        flash('Safe index apply queued on the ops worker.', 'success')
        return redirect(url_for("platform_routes.platform_operations"))
    indexes = result.get('indexes') or {}
    applied = indexes.get("applied", 0)
    failed = indexes.get("failed", 0)

    if applied:
        flash(f"Applied {applied} safe optimization(s).", "success")
    if failed:
        flash(f"{failed} optimization(s) failed — see details below.", "error")
    if not applied and not failed:
        flash("No pending safe optimizations to apply.", "info")
    return redirect(url_for("platform_routes.platform_operations"))


@platform_routes.route("/platform/operations/run-full", methods=["POST"])
@platform_routes.route("/platform/db-health/run-full", methods=["POST"])
@login_required
@platform_permission_required("operations.view")
def platform_operations_run_full():
    """One-click: Postgres + Mongo + AI + integrations maintenance."""
    from utils.maintenance_window import is_peak_traffic_window
    from utils.platform_ops import run_full_platform_ops

    confirm = (request.form.get("confirm") or "").strip().upper()
    if confirm != "MAINTAIN":
        flash('Type MAINTAIN in the confirmation box to run full platform maintenance.', "warning")
        return redirect(url_for("platform_routes.platform_operations"))

    if is_peak_traffic_window():
        flash(
            "Peak traffic window is active — full maintenance may impact live users. "
            "Proceed only if necessary; prefer off-peak for heavy DDL.",
            "warning",
        )

    restart = request.form.get("restart") == "1"
    apply_manual = request.form.get("apply_manual") == "1"
    clear_ai = request.form.get("clear_ai_cache") == "1"
    try:
        result = run_full_platform_ops(
            actor_user_id=current_user.id,
            restart=restart,
            apply_manual=apply_manual,
            clear_ai_cache_all=clear_ai,
        )
        step_lines = [
            f"{'✓' if s.get('ok') else '✗'} {s.get('step', '?')}: {s.get('message', '')}"
            for s in result.get("steps", [])
        ]
        summary = f"Full platform ops {result.get('status')} — {len(result.get('steps', []))} step(s)."
        if restart and result.get("postgres", {}).get("restart_status") == "scheduled":
            summary += " App restart scheduled (~30s)."
        flash(summary, "success" if result.get("status") == "success" else "warning")
        for line in step_lines[:10]:
            flash(line, "info")
    except Exception as exc:
        logger.error("Full platform ops failed: %s", exc, exc_info=True)
        flash(f"Full platform ops failed: {exc}", "error")
    return redirect(url_for("platform_routes.platform_operations"))


@platform_routes.route("/platform/operations/apply-manual", methods=["POST"])
@platform_routes.route("/platform/db-health/apply-manual", methods=["POST"])
@login_required
@platform_permission_required("operations.view")
def platform_operations_apply_manual():
    from utils.db_optimizer_agent import apply_all_manual_recommendations

    result = apply_all_manual_recommendations(None)
    applied = result.get("applied", 0)
    failed = result.get("failed", 0)
    if applied:
        flash(f"Applied {applied} manual optimization(s) (pg_trgm, FTS, etc.).", "success")
    if failed:
        flash(f"{failed} manual optimization(s) failed.", "error")
    if not applied and not failed:
        flash("No pending manual optimizations.", "info")
    return redirect(url_for("platform_routes.platform_operations"))


@platform_routes.route("/platform/operations/apply-all", methods=["POST"])
@platform_routes.route("/platform/db-health/apply-all", methods=["POST"])
@login_required
@platform_permission_required("operations.view")
def platform_operations_apply_all():
    from utils.db_optimizer_agent import apply_all_pending_recommendations

    result = apply_all_pending_recommendations(None)
    applied = result.get("applied", 0)
    failed = result.get("failed", 0)
    if applied:
        flash(f"Applied {applied} optimization(s) (safe + manual).", "success")
    if failed:
        flash(f"{failed} optimization(s) failed.", "error")
    if not applied and not failed:
        flash("No pending optimizations to apply.", "info")
    return redirect(url_for("platform_routes.platform_operations"))


@platform_routes.route("/platform/operations/mongo/run", methods=["POST"])
@login_required
@platform_permission_required("operations.view")
def platform_ops_mongo_run():
    from utils.mongo_platform import bootstrap_mongo

    try:
        result = bootstrap_mongo(provision_tenants=True)
        flash(
            f"MongoDB maintenance {result.get('status')} — {len(result.get('steps', []))} step(s).",
            "success" if result.get("status") == "success" else "warning",
        )
    except Exception as exc:
        flash(f"MongoDB maintenance failed: {exc}", "error")
    return redirect(url_for("platform_routes.platform_operations", tab="mongo"))


@platform_routes.route("/platform/operations/ai/clear-cache", methods=["POST"])
@login_required
@platform_permission_required("operations.view")
def platform_ops_ai_clear_cache():
    from utils.ai_platform import clear_ai_cache

    expired_only = request.form.get("expired_only") == "1"
    result = clear_ai_cache(expired_only=expired_only)
    flash(
        f"Removed {result.get('removed', 0)} LearnIQ cache file(s).",
        "success" if result.get("ok") else "error",
    )
    return redirect(url_for("platform_routes.platform_operations", tab="ai"))


@platform_routes.route("/platform/operations/ai/refresh", methods=["POST"])
@login_required
@platform_permission_required("operations.view")
def platform_ops_ai_refresh():
    from utils.ai_platform import refresh_ai_engine

    try:
        status = refresh_ai_engine()
        flash(
            status.get("message", "AI engine status refreshed."),
            "success" if status.get("available") else "warning",
        )
    except Exception as exc:
        flash(str(exc), "error")
    return redirect(url_for("platform_routes.platform_operations", tab="ai"))


@platform_routes.route("/platform/operations/scheduler/run/<job_id>", methods=["POST"])
@login_required
@platform_permission_required("operations.view")
def platform_ops_run_scheduler_job(job_id: str):
    from extensions import scheduler

    if job_id not in PLATFORM_SCHEDULER_MANUAL_JOBS:
        flash(f"Job '{job_id}' cannot be run manually from the console.", "error")
        return redirect(url_for("platform_routes.platform_operations", tab="system"))

    job = scheduler.get_job(job_id)
    if not job:
        flash(f"Scheduler job '{job_id}' not found.", "error")
        return redirect(url_for("platform_routes.platform_operations", tab="system"))
    try:
        # Run the job func within app context
        from flask import current_app
        with current_app.app_context():
            job.func()
        flash(f"Scheduler job '{job_id}' executed successfully.", "success")
    except Exception as exc:
        logger.error("Failed to run scheduler job %s: %s", job_id, exc)
        flash(f"Failed to run job '{job_id}': {exc}", "error")
    return redirect(url_for("platform_routes.platform_operations", tab="system"))


@platform_routes.route("/platform/operations/metrics-api")
@login_required
@platform_permission_required("operations.view")
def platform_operations_metrics_api():
    """Returns JSON payload of system health & metrics for live polling."""
    from utils.platform_metrics_api import get_cached_metrics_api_payload

    try:
        payload = get_cached_metrics_api_payload()
        return {"ok": True, "metrics": payload}
    except Exception as exc:
        logger.error("Failed to gather platform metrics: %s", exc)
        return {"ok": False, "error": str(exc)}, 500


@platform_routes.route("/platform/operations/agents-api")
@login_required
@platform_permission_required("operations.view")
def platform_ops_agents_api():
    """JSON snapshot of all ops agent reports for live UI updates."""
    from utils.ops_agents import load_all_agent_reports

    return {"ok": True, "agents": load_all_agent_reports()}


@platform_routes.route("/platform/operations/agent/<domain>/run", methods=["POST"])
@login_required
@platform_permission_required("operations.view")
def platform_ops_agent_run(domain: str):
    from utils.ops_agents import VALID_DOMAINS, run_ops_agent

    if domain not in VALID_DOMAINS:
        flash("Unknown ops agent.", "error")
        return redirect(url_for("platform_routes.platform_operations"))

    tab = domain if domain != "overview" else "overview"
    try:
        report = run_ops_agent(domain, force=True, use_ai=True)
        flash(
            f"{report['agent_name']} updated — status: {report['status']} "
            f"(score {report.get('health_score', '—')}/100).",
            "success" if report["status"] == "healthy" else "warning",
        )
    except Exception as exc:
        logger.error("Ops agent run failed: %s", exc)
        flash(f"Agent refresh failed: {exc}", "error")
    return redirect(url_for("platform_routes.platform_operations", tab=tab))


@platform_routes.route("/platform/operations/agent/<domain>/act", methods=["POST"])
@login_required
@platform_permission_required("operations.view")
def platform_ops_agent_act(domain: str):
    from utils.ops_agents import VALID_DOMAINS, execute_agent_action

    if domain not in VALID_DOMAINS:
        flash("Unknown ops agent.", "error")
        return redirect(url_for("platform_routes.platform_operations"))

    action_id = (request.form.get("action_id") or "").strip()
    tab = domain if domain != "overview" else "overview"
    ok, message = execute_agent_action(
        domain,
        action_id,
        actor_user_id=current_user.id,
    )
    flash(message, "success" if ok else "error")
    return redirect(url_for("platform_routes.platform_operations", tab=tab))
