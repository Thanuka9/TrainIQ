"""Welcome + onboarding drip emails for new trial organizations."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

from flask import render_template, url_for
from flask_mail import Message

logger = logging.getLogger(__name__)

DRIP_SCHEDULE = (
    (1, "onboarding_drip_1_at", "onboarding_drip_day1.html", "Upload your first course on TrainIQ"),
    (3, "onboarding_drip_3_at", "onboarding_drip_day3.html", "Invite your pilot team to TrainIQ"),
    (7, "onboarding_drip_7_at", "onboarding_drip_day7.html", "Run your first proctored exam"),
)


def _super_admin_recipients(tenant) -> list[str]:
    from models import User

    emails = [
        u.employee_email
        for u in User.query.filter_by(tenant_id=tenant.id, is_super_admin=True).all()
        if u.employee_email
    ]
    if not emails and tenant.billing_email:
        emails = [tenant.billing_email]
    return emails


def send_welcome_email(tenant, *, admin_user=None) -> bool:
    from extensions import db, mail

    recipients = _super_admin_recipients(tenant)
    if not recipients:
        return False

    dashboard_url = url_for("general_routes.dashboard", _external=True)
    checklist_url = dashboard_url
    msg = Message(
        subject=f"Welcome to TrainIQ — {tenant.name} is ready",
        recipients=recipients,
    )
    msg.body = (
        f"Welcome to TrainIQ! Your organization {tenant.name} is live.\n"
        f"Office Key: {tenant.office_key}\n"
        f"Dashboard: {dashboard_url}\n"
    )
    msg.html = render_template(
        "emails/onboarding_welcome.html",
        tenant=tenant,
        admin_user=admin_user,
        dashboard_url=dashboard_url,
        checklist_url=checklist_url,
    )
    try:
        mail.send(msg)
        tenant.onboarding_welcome_at = datetime.utcnow()
        db.session.commit()
        logger.info("Welcome email sent for tenant %s", tenant.id)
        return True
    except Exception as exc:
        db.session.rollback()
        logger.error("Welcome email failed tenant %s: %s", tenant.id, exc)
        return False


def _send_drip(tenant, *, template: str, subject: str, day: int) -> bool:
    from extensions import mail

    recipients = _super_admin_recipients(tenant)
    if not recipients:
        return False

    from utils.trial_checklist import get_trial_checklist

    checklist = get_trial_checklist(tenant)
    dashboard_url = url_for("general_routes.dashboard", _external=True)
    msg = Message(subject=subject, recipients=recipients)
    msg.html = render_template(
        f"emails/{template}",
        tenant=tenant,
        day=day,
        checklist=checklist,
        dashboard_url=dashboard_url,
    )
    try:
        mail.send(msg)
        return True
    except Exception as exc:
        logger.error("Onboarding drip day %s failed tenant %s: %s", day, tenant.id, exc)
        return False


def process_onboarding_drip_emails() -> dict:
    """Send day 1 / 3 / 7 onboarding drips based on tenant.created_at."""
    from extensions import db
    from models import Tenant

    stats = {"day_1": 0, "day_3": 0, "day_7": 0}
    now = datetime.utcnow()

    tenants = Tenant.query.filter(
        Tenant.plan == "trial",
        Tenant.status.in_(("trial", "active")),
        Tenant.onboarding_welcome_at.isnot(None),
    ).all()

    for tenant in tenants:
        created = getattr(tenant, "created_at", None) or now
        age_days = (now - created).days

        for min_day, attr, template, subject in DRIP_SCHEDULE:
            if age_days < min_day:
                continue
            if getattr(tenant, attr, None):
                continue
            if _send_drip(tenant, template=template, subject=subject, day=min_day):
                setattr(tenant, attr, now)
                stats[f"day_{min_day}"] += 1

    if any(stats.values()):
        db.session.commit()
    return stats
