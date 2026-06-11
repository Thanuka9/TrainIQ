"""Multi-tenant helpers for TrainIQ SaaS."""
from __future__ import annotations

import os
import random
import string

from flask import abort, session
from flask_login import current_user
from sqlalchemy import text


def generate_office_key(length=10):
    chars = string.ascii_uppercase + string.digits
    return "".join(random.choice(chars) for _ in range(length))


def trainiq_staff_domains():
    raw = os.getenv("TRAINIQ_STAFF_DOMAINS", "trainiq.com")
    return {d.strip().lower() for d in raw.split(",") if d.strip()}


def email_domain(email: str) -> str:
    return (email or "").split("@")[-1].lower().strip()


def is_platform_ceo(user=None) -> bool:
    from utils.platform_ceo import is_platform_ceo as _ceo_check

    return _ceo_check(user)


def is_trainiq_staff(user=None) -> bool:
    """TrainIQ platform staff (or CEO) may access any tenant via office-key login."""
    user = user or current_user
    if not user or not getattr(user, "is_authenticated", False):
        return False
    if is_platform_ceo(user):
        return True
    return email_domain(getattr(user, "employee_email", "")) in trainiq_staff_domains()


def parse_domain_list(raw: str) -> list[str]:
    return [d.strip().lower() for d in (raw or "").split(",") if d.strip()]


def domain_matches_allowed(email: str, allowed_domain: str) -> bool:
    """Exact match of registrant email domain against tenant allowed domains."""
    dom = email_domain(email)
    if not dom:
        return False
    allowed = parse_domain_list(allowed_domain)
    if not allowed:
        return True
    return dom in allowed


def host_matches_allowed(host: str, allowed_domain: str) -> bool:
    host = (host or "").split(":")[0].lower().strip()
    return host in parse_domain_list(allowed_domain)


def user_tenant_id(user=None):
    """Active tenant for queries — respects TrainIQ support sessions."""
    user = user or current_user
    if not user or not getattr(user, "is_authenticated", False) or not user.is_authenticated:
        return None
    if session.get("platform_support") and session.get("tenant_id"):
        return session.get("tenant_id")
    return getattr(user, "tenant_id", None)


def set_active_tenant_session(tenant, *, platform_support=False):
    session["tenant_id"] = tenant.id
    session["tenant_name"] = tenant.name
    session["platform_support"] = bool(platform_support)


def filter_by_user_tenant(query, model, user=None):
    """Apply tenant_id filter. Fail-closed when user has no tenant context."""
    tid = user_tenant_id(user)
    if tid is not None and hasattr(model, "tenant_id"):
        return query.filter(model.tenant_id == tid)
    if hasattr(model, "tenant_id"):
        user = user or current_user
        if getattr(user, "is_authenticated", False) and user.is_authenticated:
            return query.filter(text("1=0"))
    return query


def normalize_office_key(key):
    return (key or "").strip().upper() or None


def tenant_users_query(user=None):
    from models import User
    return filter_by_user_tenant(User.query, User, user)


def tenant_departments_query(user=None):
    from models import Department
    return filter_by_user_tenant(Department.query, Department, user)


def tenant_clients_query(user=None):
    from models import Client
    return filter_by_user_tenant(Client.query, Client, user)


def tenant_exams_query(user=None):
    from models import Exam
    return filter_by_user_tenant(Exam.query, Exam, user)


def tenant_courses_query(user=None):
    from models import StudyMaterial
    return filter_by_user_tenant(StudyMaterial.query, StudyMaterial, user)


def tenant_categories_query(user=None):
    from models import Category
    return filter_by_user_tenant(Category.query, Category, user)


def tenant_levels_query(user=None):
    from models import Level
    return filter_by_user_tenant(Level.query, Level, user)


def tenant_areas_query(user=None):
    from models import Area
    return filter_by_user_tenant(Area.query, Area, user)


def tenant_designations_query(user=None):
    from models import Designation
    return filter_by_user_tenant(Designation.query, Designation, user)


def require_user_in_tenant(user_id, actor=None):
    from models import User
    user = User.query.get_or_404(user_id)
    assert_user_in_tenant(user, actor)
    return user


def scope_exam_access_requests(query, user=None):
    from models import ExamAccessRequest, User
    tid = user_tenant_id(user)
    if tid is None:
        return query
    return query.join(User, ExamAccessRequest.user_id == User.id).filter(User.tenant_id == tid)


def scope_support_tickets(query, user=None):
    from models import SupportTicket, User
    tid = user_tenant_id(user)
    if tid is None:
        return query
    return query.join(User, SupportTicket.user_id == User.id).filter(User.tenant_id == tid)


def tenant_category_names(user=None):
    """Ordered category names for the active tenant (charts, comparisons)."""
    from models import Category
    return [
        c.name for c in tenant_categories_query(user).order_by(Category.name).all() if c.name
    ]


def scope_audit_logs(query, user=None):
    from models import AuditLog, User
    tid = user_tenant_id(user)
    if tid is None:
        return query
    return query.outerjoin(User, AuditLog.actor_user_id == User.id).filter(
        (User.tenant_id == tid) | (AuditLog.actor_user_id.is_(None))
    )


def tenant_user_id_list(user=None):
    from models import User
    tid = user_tenant_id(user)
    if tid is None:
        return None
    return [row[0] for row in tenant_users_query(user).with_entities(User.id).all()]


def filter_scores_by_tenant(query, user=None):
    ids = tenant_user_id_list(user)
    if ids is None:
        return query
    if not ids:
        return query.filter(text("1=0"))
    from models import UserScore
    return query.filter(UserScore.user_id.in_(ids))


def filter_progress_by_tenant(query, user=None):
    ids = tenant_user_id_list(user)
    if ids is None:
        return query
    if not ids:
        return query.filter(text("1=0"))
    from models import UserProgress
    return query.filter(UserProgress.user_id.in_(ids))


def assert_user_in_tenant(user, actor=None):
    if user is None:
        abort(404)
    tid = user_tenant_id(actor)
    if tid is not None and user.tenant_id is not None and user.tenant_id != tid:
        actor_user = actor or current_user
        if not (is_trainiq_staff(actor_user) and session.get("platform_support")):
            abort(403)


def assert_tenant_access(resource, user=None):
    if resource is None:
        abort(404)
    tid = user_tenant_id(user)
    res_tid = getattr(resource, "tenant_id", None)
    if tid is not None and res_tid is not None and res_tid != tid:
        user = user or current_user
        if is_trainiq_staff(user) and session.get("platform_support"):
            return
        abort(403)


def count_tenant_super_admins(tenant_id=None, user=None):
    from models import User
    tid = tenant_id or user_tenant_id(user)
    if not tid:
        return 0
    return User.query.filter_by(tenant_id=tid, is_super_admin=True).count()
