"""Organization announcements — fetch and broadcast."""
from __future__ import annotations

from datetime import datetime

from extensions import db


def active_announcements_for_tenant(tenant_id: int | None, *, limit: int = 10) -> list[dict]:
    """Return visible announcements for the user dashboard."""
    from models import Announcement

    if not tenant_id:
        return []

    now = datetime.utcnow()
    rows = (
        Announcement.query.filter_by(tenant_id=tenant_id, is_active=True)
        .filter(db.or_(Announcement.expires_at.is_(None), Announcement.expires_at > now))
        .order_by(Announcement.is_pinned.desc(), Announcement.published_at.desc())
        .limit(limit)
        .all()
    )
    return [a.dashboard_dict() for a in rows if a.is_visible()]


def broadcast_announcement(announcement, *, notify: bool = True) -> None:
    """Optionally ping all verified tenant users via in-app notification."""
    if not notify or not announcement:
        return

    from flask import url_for
    from models import User
    from utils.notifications import create_notification

    users = User.query.filter_by(
        tenant_id=announcement.tenant_id, is_verified=True
    ).filter(User.deleted_at.is_(None)).all()

    link = url_for('general_routes.dashboard')
    for u in users:
        create_notification(
            u.id,
            announcement.title,
            (announcement.message or '')[:200],
            category='info',
            link_url=link,
            icon='bullhorn',
            dedupe_key=f"announcement_{announcement.id}_{u.id}",
            commit=False,
        )
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
