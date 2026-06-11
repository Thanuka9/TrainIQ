"""Platform-wide metrics for TrainIQ CEO / staff console."""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import func

from utils.billing_plans import PLANS, TRIAL_DAYS


def _plan_mrr(tenant) -> float:
    plan_id = (getattr(tenant, "plan", "") or "trial").lower()
    if plan_id in ("trial", "enterprise"):
        return 0.0
    plan = PLANS.get(plan_id)
    if not plan or not plan.get("price_monthly"):
        return 0.0
    cycle = (getattr(tenant, "billing_cycle", "") or "monthly").lower()
    if cycle == "yearly":
        return float(plan.get("price_yearly_per_month") or 0)
    return float(plan["price_monthly"])


def _count_by_tenant(model, tenant_id_field="tenant_id"):
    from extensions import db

    col = getattr(model, tenant_id_field)
    rows = db.session.query(col, func.count()).group_by(col).all()
    return {tid: cnt for tid, cnt in rows if tid is not None}


def get_platform_alerts() -> list[dict]:
    """Actionable alerts for the CEO dashboard."""
    from models import SupportTicket, Tenant, User

    now = datetime.utcnow()
    alerts: list[dict] = []

    expiring = Tenant.query.filter(
        Tenant.plan == "trial",
        Tenant.trial_ends_at.isnot(None),
        Tenant.trial_ends_at <= now + timedelta(days=7),
        Tenant.trial_ends_at > now,
    ).order_by(Tenant.trial_ends_at).limit(10).all()
    for t in expiring:
        days = (t.trial_ends_at - now).days
        alerts.append(
            {
                "level": "warning",
                "icon": "clock",
                "title": f"Trial expiring — {t.name}",
                "detail": f"Ends in {days}d ({t.office_key})",
                "tenant_id": t.id,
            }
        )

    for t in Tenant.query.filter_by(status="suspended").limit(5):
        alerts.append(
            {
                "level": "danger",
                "icon": "pause",
                "title": f"Suspended — {t.name}",
                "detail": (t.suspended_reason or "No reason recorded")[:80],
                "tenant_id": t.id,
            }
        )

    open_tickets = (
        SupportTicket.query.filter(SupportTicket.status.in_(("Open", "In Progress")))
        .order_by(SupportTicket.created_at.desc())
        .limit(5)
        .all()
    )
    for tk in open_tickets:
        org = tk.user.tenant.name if tk.user and tk.user.tenant else "Unknown"
        alerts.append(
            {
                "level": "info",
                "icon": "headset",
                "title": f"Support: {tk.title[:50]}",
                "detail": f"{org} · {tk.status}",
                "ticket_id": tk.id,
            }
        )

    locked = User.query.filter_by(is_locked=True).count()
    if locked:
        alerts.append(
            {
                "level": "warning",
                "icon": "lock",
                "title": f"{locked} locked account(s)",
                "detail": "Review in Security console",
            }
        )

    return alerts[:15]


def get_platform_analytics() -> dict:
    from extensions import db
    from models import (
        AuditLog,
        Client,
        Department,
        Exam,
        ExamAccessRequest,
        Question,
        SpecialExamRecord,
        StudyMaterial,
        SupportTicket,
        Task,
        Tenant,
        TenantInvite,
        User,
        UserScore,
    )

    tenants = Tenant.query.order_by(Tenant.created_at.desc()).all()
    now = datetime.utcnow()
    week_ago = now - timedelta(days=7)
    month_ago = now - timedelta(days=30)

    user_by_tenant = _count_by_tenant(User)
    course_by_tenant = _count_by_tenant(StudyMaterial)
    exam_by_tenant = _count_by_tenant(Exam)
    task_by_tenant = _count_by_tenant(Task)

    total_users = User.query.filter(User.deleted_at.is_(None)).count()
    active_users = User.query.filter_by(is_verified=True).filter(User.deleted_at.is_(None)).count()
    new_users_7d = User.query.filter(User.join_date >= week_ago.date()).count()
    new_users_30d = User.query.filter(User.join_date >= month_ago.date()).count()
    locked_users = User.query.filter_by(is_locked=True).count()
    super_admins = User.query.filter_by(is_super_admin=True).count()

    by_plan: dict[str, int] = {}
    by_status: dict[str, int] = {}
    trial_count = 0
    paid_count = 0
    mrr = 0.0
    revenue_by_plan: dict[str, float] = {}

    tenant_rows = []
    for t in tenants:
        pid = (t.plan or "trial").lower()
        st = (t.status or "active").lower()
        by_plan[pid] = by_plan.get(pid, 0) + 1
        by_status[st] = by_status.get(st, 0) + 1
        tmrr = _plan_mrr(t)
        if pid == "trial":
            trial_count += 1
        elif pid != "enterprise" and st == "active":
            paid_count += 1
            mrr += tmrr
            revenue_by_plan[pid] = revenue_by_plan.get(pid, 0.0) + tmrr

        tenant_rows.append(
            {
                "tenant": t,
                "users": user_by_tenant.get(t.id, 0),
                "courses": course_by_tenant.get(t.id, 0),
                "exams": exam_by_tenant.get(t.id, 0),
                "tasks": task_by_tenant.get(t.id, 0),
                "mrr": tmrr,
            }
        )

    expiring_trials = Tenant.query.filter(
        Tenant.plan == "trial",
        Tenant.trial_ends_at.isnot(None),
        Tenant.trial_ends_at <= now + timedelta(days=7),
        Tenant.trial_ends_at > now,
    ).count()

    open_support = SupportTicket.query.filter(
        SupportTicket.status.in_(("Open", "In Progress"))
    ).count()
    total_support = SupportTicket.query.count()

    pending_invites = TenantInvite.query.filter(TenantInvite.used_at.is_(None)).count()
    pending_exam_requests = ExamAccessRequest.query.filter_by(status="pending").count()

    failed_logins_7d = AuditLog.query.filter(
        AuditLog.event_type == "FAILED_LOGIN",
        AuditLog.created_at >= week_ago,
    ).count()
    audit_today = AuditLog.query.filter(
        AuditLog.created_at >= datetime.combine(now.date(), datetime.min.time())
    ).count()

    # User growth — last 6 months
    growth_labels = []
    growth_values = []
    for i in range(5, -1, -1):
        month_start = (now.replace(day=1) - timedelta(days=i * 28)).replace(day=1)
        if month_start.month == 12:
            month_end = month_start.replace(year=month_start.year + 1, month=1)
        else:
            month_end = month_start.replace(month=month_start.month + 1)
        label = month_start.strftime("%b %Y")
        cnt = User.query.filter(
            User.join_date >= month_start.date(),
            User.join_date < month_end.date(),
        ).count()
        growth_labels.append(label)
        growth_values.append(cnt)

    recent_activity = (
        AuditLog.query.order_by(AuditLog.created_at.desc()).limit(20).all()
    )

    return {
        "total_tenants": len(tenants),
        "total_users": total_users,
        "active_users": active_users,
        "new_users_7d": new_users_7d,
        "new_users_30d": new_users_30d,
        "locked_users": locked_users,
        "super_admins": super_admins,
        "trial_tenants": trial_count,
        "paid_tenants": paid_count,
        "suspended_tenants": by_status.get("suspended", 0),
        "expired_tenants": by_status.get("expired", 0),
        "expiring_trials_7d": expiring_trials,
        "estimated_mrr": round(mrr, 2),
        "estimated_arr": round(mrr * 12, 2),
        "revenue_by_plan": revenue_by_plan,
        "by_plan": by_plan,
        "by_status": by_status,
        "tenant_rows": tenant_rows,
        "trial_days": TRIAL_DAYS,
        # Content & operations
        "total_courses": StudyMaterial.query.count(),
        "total_exams": Exam.query.count(),
        "total_questions": Question.query.count(),
        "total_tasks": Task.query.count(),
        "total_clients": Client.query.count(),
        "total_departments": Department.query.count(),
        "exam_attempts": UserScore.query.count(),
        "special_exam_records": SpecialExamRecord.query.count(),
        "open_support": open_support,
        "total_support": total_support,
        "pending_invites": pending_invites,
        "pending_exam_requests": pending_exam_requests,
        "failed_logins_7d": failed_logins_7d,
        "audit_events_today": audit_today,
        "user_growth_labels": growth_labels,
        "user_growth_values": growth_values,
        "recent_activity": recent_activity,
        "alerts": get_platform_alerts(),
    }


def get_revenue_analytics() -> dict:
    """Detailed revenue breakdown for platform revenue page."""
    from models import Tenant

    stats = get_platform_analytics()
    rows = []
    for row in stats["tenant_rows"]:
        t = row["tenant"]
        if row["mrr"] <= 0:
            continue
        rows.append(
            {
                "tenant": t,
                "plan": t.plan,
                "cycle": t.billing_cycle or "monthly",
                "users": row["users"],
                "max_users": t.max_users,
                "mrr": row["mrr"],
                "arr": round(row["mrr"] * 12, 2),
            }
        )
    rows.sort(key=lambda r: r["mrr"], reverse=True)

    plan_totals = []
    for plan_id, amount in sorted(
        stats["revenue_by_plan"].items(),
        key=lambda x: x[1],
        reverse=True,
    ):
        plan = PLANS.get(plan_id, {})
        plan_totals.append(
            {
                "plan_id": plan_id,
                "name": plan.get("name", plan_id),
                "mrr": round(amount, 2),
                "tenants": stats["by_plan"].get(plan_id, 0),
            }
        )

    return {
        **{k: stats[k] for k in (
            "estimated_mrr", "estimated_arr", "paid_tenants",
            "trial_tenants", "by_plan", "revenue_by_plan",
        )},
        "paying_rows": rows,
        "plan_totals": plan_totals,
    }


def get_tenant_detail(tenant_id: int) -> dict | None:
    """360° view of a single tenant for CEO console."""
    from models import (
        AuditLog,
        Client,
        Department,
        Designation,
        Exam,
        ExamAccessRequest,
        StudyMaterial,
        SupportTicket,
        Task,
        Tenant,
        TenantInvite,
        User,
        UserScore,
    )

    tenant = Tenant.query.get(tenant_id)
    if not tenant:
        return None

    users = User.query.filter_by(tenant_id=tenant_id).filter(User.deleted_at.is_(None))
    user_list = users.order_by(User.join_date.desc()).limit(50).all()

    open_tickets = (
        SupportTicket.query.join(User, SupportTicket.user_id == User.id)
        .filter(User.tenant_id == tenant_id)
        .filter(SupportTicket.status.in_(("Open", "In Progress")))
        .order_by(SupportTicket.created_at.desc())
        .limit(10)
        .all()
    )

    recent_audit = (
        AuditLog.query.join(User, AuditLog.actor_user_id == User.id)
        .filter(User.tenant_id == tenant_id)
        .order_by(AuditLog.created_at.desc())
        .limit(15)
        .all()
    )

    pending_invites = (
        TenantInvite.query.filter_by(tenant_id=tenant_id)
        .filter(TenantInvite.used_at.is_(None))
        .order_by(TenantInvite.created_at.desc())
        .limit(10)
        .all()
    )

    return {
        "tenant": tenant,
        "mrr": _plan_mrr(tenant),
        "stats": {
            "users": users.count(),
            "verified": users.filter_by(is_verified=True).count(),
            "locked": users.filter_by(is_locked=True).count(),
            "super_admins": users.filter_by(is_super_admin=True).count(),
            "courses": StudyMaterial.query.filter_by(tenant_id=tenant_id).count(),
            "exams": Exam.query.filter_by(tenant_id=tenant_id).count(),
            "tasks": Task.query.filter_by(tenant_id=tenant_id).count(),
            "clients": Client.query.filter_by(tenant_id=tenant_id).count(),
            "departments": Department.query.filter_by(tenant_id=tenant_id).count(),
            "designations": Designation.query.filter_by(tenant_id=tenant_id).count(),
            "exam_attempts": UserScore.query.join(User).filter(User.tenant_id == tenant_id).count(),
            "open_support": len(open_tickets),
            "pending_exam_requests": ExamAccessRequest.query.join(User).filter(
                User.tenant_id == tenant_id, ExamAccessRequest.status == "pending"
            ).count(),
        },
        "users": user_list,
        "open_tickets": open_tickets,
        "recent_audit": recent_audit,
        "pending_invites": pending_invites,
        "plan_info": PLANS.get((tenant.plan or "trial").lower(), {}),
    }


def search_platform_users(
    q: str = "",
    tenant_id: int | None = None,
    status: str = "",
    limit: int = 100,
) -> list[dict]:
    """Cross-tenant user search for CEO."""
    from extensions import db
    from models import Tenant, User

    query = User.query.filter(User.deleted_at.is_(None))
    if tenant_id:
        query = query.filter_by(tenant_id=tenant_id)
    if status == "verified":
        query = query.filter_by(is_verified=True)
    elif status == "unverified":
        query = query.filter_by(is_verified=False)
    elif status == "locked":
        query = query.filter_by(is_locked=True)
    elif status == "super_admin":
        query = query.filter_by(is_super_admin=True)

    if q:
        like = f"%{q.strip()}%"
        query = query.filter(
            db.or_(
                User.first_name.ilike(like),
                User.last_name.ilike(like),
                User.employee_email.ilike(like),
                User.employee_id.ilike(like),
            )
        )

    rows = []
    tenant_cache: dict[int, Tenant | None] = {}
    for u in query.order_by(User.join_date.desc()).limit(limit).all():
        if u.tenant_id not in tenant_cache:
            tenant_cache[u.tenant_id] = Tenant.query.get(u.tenant_id) if u.tenant_id else None
        rows.append({"user": u, "tenant": tenant_cache[u.tenant_id]})
    return rows


def get_platform_support_queue(status: str = "open", limit: int = 100) -> list[dict]:
    from models import SupportTicket, User

    query = SupportTicket.query.join(User, SupportTicket.user_id == User.id)
    if status == "open":
        query = query.filter(SupportTicket.status.in_(("Open", "In Progress")))
    elif status and status != "all":
        query = query.filter(SupportTicket.status == status)

    rows = []
    for tk in query.order_by(SupportTicket.created_at.desc()).limit(limit).all():
        rows.append({"ticket": tk, "user": tk.user, "tenant": tk.user.tenant if tk.user else None})
    return rows


def get_platform_security_feed(limit: int = 100, event_type: str = "") -> dict:
    from models import AuditLog, User

    week_ago = datetime.utcnow() - timedelta(days=7)
    base = AuditLog.query
    if event_type:
        base = base.filter(AuditLog.event_type == event_type)

    events = base.order_by(AuditLog.created_at.desc()).limit(limit).all()

    security_types = (
        "FAILED_LOGIN", "USER_LOGIN", "USER_LOGOUT",
        "PASSWORD_RESET", "ACCOUNT_LOCKED",
    )
    counts = {}
    for et in security_types:
        counts[et] = AuditLog.query.filter(
            AuditLog.event_type == et,
            AuditLog.created_at >= week_ago,
        ).count()

    locked_users = User.query.filter_by(is_locked=True).limit(20).all()

    return {
        "events": events,
        "counts_7d": counts,
        "locked_users": locked_users,
        "failed_logins_7d": counts.get("FAILED_LOGIN", 0),
    }


def get_platform_activity_feed(limit: int = 100) -> list[dict]:
    """Recent platform-wide activity for CEO activity console."""
    from models import AuditLog, User

    platform_types = (
        "PLATFORM_ENTER_TENANT",
        "PLATFORM_EXIT_TENANT",
        "PLAN_UPGRADE",
        "USER_REGISTER",
        "TENANT_CREATED",
        "FAILED_LOGIN",
        "USER_LOGIN",
    )
    events = (
        AuditLog.query.filter(AuditLog.event_type.in_(platform_types))
        .order_by(AuditLog.created_at.desc())
        .limit(limit)
        .all()
    )
    rows = []
    for ev in events:
        actor = User.query.get(ev.actor_user_id) if ev.actor_user_id else None
        desc = ev.description or {}
        rows.append(
            {
                "event": ev,
                "actor": actor,
                "summary": _activity_summary(ev, actor, desc),
            }
        )
    return rows


def _activity_summary(ev, actor, desc) -> str:
    email = actor.employee_email if actor else "System"
    et = ev.event_type
    if et == "PLATFORM_ENTER_TENANT":
        return f"{email} entered support mode → {desc.get('tenant_name', 'org')}"
    if et == "PLATFORM_EXIT_TENANT":
        return f"{email} exited support mode"
    if et == "PLAN_UPGRADE":
        return f"{email} changed plan — {desc.get('details', '')}"
    if et == "USER_REGISTER":
        return f"New registration: {desc.get('email', email)}"
    if et == "FAILED_LOGIN":
        return f"Failed login attempt ({desc.get('email', 'unknown')})"
    return f"{et} — {email}"
