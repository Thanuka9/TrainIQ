"""Weekly/daily email digests for learners and admins."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

from flask import render_template, url_for
from flask_mail import Message

logger = logging.getLogger(__name__)


def _active_users_since(days: int = 7):
    from models import User, AuditLog

    since = datetime.utcnow() - timedelta(days=days)
    active_ids = {
        row.user_id
        for row in AuditLog.query.filter(
            AuditLog.created_at >= since,
            AuditLog.user_id.isnot(None),
        ).with_entities(AuditLog.user_id).distinct()
    }
    if not active_ids:
        return []
    return User.query.filter(User.id.in_(active_ids), User.is_verified.is_(True)).all()


def build_learner_digest(user) -> dict:
    """Summarize progress for a single learner."""
    from models import UserProgress, Task

    progress_count = UserProgress.query.filter_by(user_id=user.id).count()
    open_tasks = Task.query.filter_by(assigned_to=user.id, status="open").count()
    return {
        "user": user,
        "progress_count": progress_count,
        "open_tasks": open_tasks,
        "dashboard_url": url_for("general_routes.dashboard", _external=True),
    }


def send_learner_weekly_digests(mail) -> int:
    """Send weekly activity digest to recently active learners."""
    sent = 0
    for user in _active_users_since(14):
        if getattr(user, "email_digest_opt_out", False):
            continue
        digest = build_learner_digest(user)
        if not digest["progress_count"] and not digest["open_tasks"]:
            continue
        msg = Message(
            subject="Your TrainIQ weekly summary",
            recipients=[user.employee_email],
        )
        msg.body = (
            f"Hi {user.first_name},\n\n"
            f"Course progress items: {digest['progress_count']}\n"
            f"Open tasks: {digest['open_tasks']}\n\n"
            f"Dashboard: {digest['dashboard_url']}"
        )
        msg.html = render_template("emails/weekly_digest_email.html", **digest)
        try:
            mail.send(msg)
            sent += 1
        except Exception as exc:
            logger.error("Digest email failed for %s: %s", user.employee_email, exc)
    return sent


def send_admin_weekly_digests(mail) -> int:
    """Send tenant admin summary to super admins."""
    from models import User, Tenant

    sent = 0
    admins = User.query.filter_by(is_super_admin=True, is_verified=True).all()
    for admin in admins:
        tenant = Tenant.query.get(admin.tenant_id)
        if not tenant:
            continue
        from models import User as U
        user_count = U.query.filter_by(tenant_id=tenant.id).count()
        msg = Message(
            subject=f"{tenant.name} — weekly TrainIQ summary",
            recipients=[admin.employee_email],
        )
        msg.body = f"Team members: {user_count}\nAdmin dashboard: {url_for('admin_routes.admin_dashboard', _external=True)}"
        msg.html = render_template(
            "emails/admin_weekly_digest_email.html",
            admin=admin,
            tenant=tenant,
            user_count=user_count,
            admin_url=url_for("admin_routes.admin_dashboard", _external=True),
        )
        try:
            mail.send(msg)
            sent += 1
        except Exception as exc:
            logger.error("Admin digest failed for %s: %s", admin.employee_email, exc)
    return sent


def process_email_digests():
    """Run all digest jobs (called from APScheduler)."""
    from extensions import mail

    learner = send_learner_weekly_digests(mail)
    admin = send_admin_weekly_digests(mail)
    return {"learner": learner, "admin": admin}
