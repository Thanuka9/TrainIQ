"""In-app notification helpers."""
from __future__ import annotations

import logging
from datetime import datetime

from extensions import db

logger = logging.getLogger(__name__)


def create_notification(
    user_id: int,
    title: str,
    body: str = "",
    *,
    category: str = "info",
    link_url: str | None = None,
    icon: str | None = None,
    dedupe_key: str | None = None,
    commit: bool = True,
) -> bool:
    """Create a notification; skip if dedupe_key matches an existing unread item."""
    from models import Notification

    if dedupe_key:
        exists = Notification.query.filter_by(
            user_id=user_id, dedupe_key=dedupe_key, is_read=False
        ).first()
        if exists:
            return False

    n = Notification(
        user_id=user_id,
        title=title[:200],
        body=body,
        category=category,
        link_url=link_url,
        icon=icon or _category_icon(category),
        dedupe_key=dedupe_key,
    )
    db.session.add(n)
    if commit:
        try:
            db.session.commit()
        except Exception as exc:
            db.session.rollback()
            logger.error("Notification create failed: %s", exc)
            return False
    return True


def _category_icon(category: str) -> str:
    return {
        "success": "check-circle",
        "warning": "exclamation-triangle",
        "danger": "times-circle",
        "task": "list-check",
        "support": "headset",
        "exam": "file-alt",
        "billing": "credit-card",
        "platform": "globe",
    }.get(category, "bell")


def unread_count(user_id: int) -> int:
    from models import Notification

    return Notification.query.filter_by(user_id=user_id, is_read=False).count()


def recent_for_user(user_id: int, limit: int = 25) -> list:
    from models import Notification

    return (
        Notification.query.filter_by(user_id=user_id)
        .order_by(Notification.created_at.desc())
        .limit(limit)
        .all()
    )


def mark_read(notification_id: int, user_id: int) -> bool:
    from models import Notification

    n = Notification.query.filter_by(id=notification_id, user_id=user_id).first()
    if not n:
        return False
    n.is_read = True
    db.session.commit()
    return True


def mark_all_read(user_id: int) -> int:
    from models import Notification

    updated = (
        Notification.query.filter_by(user_id=user_id, is_read=False)
        .update({"is_read": True}, synchronize_session=False)
    )
    db.session.commit()
    return updated


def notify_tenant_super_admins(
    tenant_id: int,
    title: str,
    body: str = "",
    *,
    category: str = "info",
    link_url: str | None = None,
    icon: str | None = None,
    dedupe_key: str | None = None,
):
    from models import User

    if not tenant_id:
        return
    admins = User.query.filter_by(
        tenant_id=tenant_id, is_super_admin=True, is_verified=True
    ).all()
    for admin in admins:
        key = f"{dedupe_key}:{admin.id}" if dedupe_key else None
        create_notification(
            admin.id,
            title,
            body,
            category=category,
            link_url=link_url,
            icon=icon,
            dedupe_key=key,
            commit=False,
        )
    try:
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        logger.error("Bulk admin notify failed: %s", exc)


def sync_user_notifications(user) -> None:
    """Generate system alerts (trial, seat limits) for admins — idempotent via dedupe_key."""
    if not user or not getattr(user, "id", None):
        return

    from flask import url_for

    tenant = getattr(user, "tenant", None)
    if not tenant:
        return

    if user.is_super_admin:
        from utils.billing_plans import is_trial_expired, trial_days_remaining, tenant_usage

        usage = tenant_usage(tenant)
        days = trial_days_remaining(tenant)
        if tenant.plan == "trial" and days is not None and 0 < days <= 7:
            create_notification(
                user.id,
                f"Trial ending in {days} day{'s' if days != 1 else ''}",
                f"Your {tenant.name} trial ends soon. Review billing to keep your team online.",
                category="warning",
                link_url=url_for("billing_routes.billing_home"),
                icon="clock",
                dedupe_key=f"trial_expiry_{tenant.id}",
                commit=False,
            )
        elif is_trial_expired(tenant) or (getattr(tenant, "status", "") or "").lower() == "expired":
            create_notification(
                user.id,
                "Trial has ended",
                "Upgrade your plan to restore full access for your organization.",
                category="danger",
                link_url=url_for("billing_routes.billing_home"),
                icon="credit-card",
                dedupe_key=f"trial_expired_{tenant.id}",
                commit=False,
            )

        if usage.get("users", 0) >= usage.get("max_users", 1):
            create_notification(
                user.id,
                "User seat limit reached",
                f"You are at {usage['users']}/{usage['max_users']} seats. Upgrade to invite more people.",
                category="warning",
                link_url=url_for("billing_routes.billing_home"),
                icon="users",
                dedupe_key=f"seat_limit_{tenant.id}",
                commit=False,
            )

    try:
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        logger.debug("sync_user_notifications: %s", exc)


def notify_trainiq_staff(user) -> None:
    """Platform staff alerts — expiring trials across all tenants."""
    from utils.tenant_utils import is_trainiq_staff
    from utils.platform_analytics import get_platform_alerts
    from flask import url_for

    if not is_trainiq_staff(user):
        return

    for alert in get_platform_alerts()[:5]:
        if alert.get("tenant_id"):
            create_notification(
                user.id,
                alert["title"],
                alert.get("detail", ""),
                category=alert.get("level", "info"),
                link_url=url_for(
                    "platform_routes.tenant_detail", tenant_id=alert["tenant_id"]
                ),
                icon=alert.get("icon", "bell"),
                dedupe_key=f"platform_alert_{alert.get('tenant_id')}_{alert.get('icon')}",
                commit=False,
            )
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
