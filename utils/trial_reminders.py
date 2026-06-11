"""Trial lifecycle emails — 7-day and 1-day reminders to Super Admins."""
from __future__ import annotations

import logging
from datetime import datetime

from flask import render_template, url_for
from flask_mail import Message

logger = logging.getLogger(__name__)


def _super_admin_recipients(tenant_id: int) -> list[str]:
    from models import User

    return [
        u.employee_email
        for u in User.query.filter_by(tenant_id=tenant_id, is_super_admin=True).all()
        if u.employee_email
    ]


def send_trial_reminder_email(tenant, *, days_left: int, usage: dict):
    from extensions import mail

    recipients = _super_admin_recipients(tenant.id)
    if not recipients:
        recipients = [tenant.billing_email] if tenant.billing_email else []
    if not recipients:
        logger.warning("No recipients for trial reminder tenant_id=%s", tenant.id)
        return False

    billing_url = url_for("billing_routes.billing_home", _external=True)
    if days_left <= 1:
        subject = f"Final day — {tenant.name} TrainIQ trial ends tomorrow"
        urgency = "final"
    else:
        subject = f"{days_left} days left on your TrainIQ trial — {tenant.name}"
        urgency = "week"

    msg = Message(subject=subject, recipients=recipients)
    msg.body = (
        f"Your TrainIQ trial for {tenant.name} ends in {days_left} day(s).\n"
        f"Seats used: {usage['users']}/{usage['max_users']}\n"
        f"Upgrade: {billing_url}\n"
    )
    msg.html = render_template(
        "emails/trial_reminder_email.html",
        tenant=tenant,
        days_left=days_left,
        usage=usage,
        billing_url=billing_url,
        urgency=urgency,
    )
    try:
        mail.send(msg)
        logger.info("Trial reminder (%sd) sent for tenant %s to %s", days_left, tenant.id, recipients)
        return True
    except Exception as exc:
        logger.error("Trial reminder email failed tenant %s: %s", tenant.id, exc)
        return False


def process_trial_reminder_emails() -> dict:
    """
    Send one 7-day and one 1-day reminder per trial tenant (Docebo-style nudges).
    Returns counts: {seven_day: n, one_day: n}.
    """
    from extensions import db
    from models import Tenant
    from utils.billing_plans import backfill_missing_trial_dates, tenant_usage, trial_days_remaining

    backfill_missing_trial_dates()

    stats = {"seven_day": 0, "one_day": 0}
    now = datetime.utcnow()

    tenants = Tenant.query.filter(
        Tenant.plan == "trial",
        Tenant.status.in_(("trial", "active")),
    ).all()

    for tenant in tenants:
        days = trial_days_remaining(tenant)
        if days is None:
            continue
        usage = tenant_usage(tenant)

        # 7-day window: fire once when 2–7 days remain
        if 2 <= days <= 7 and not tenant.trial_reminder_7d_at:
            if send_trial_reminder_email(tenant, days_left=days, usage=usage):
                tenant.trial_reminder_7d_at = now
                stats["seven_day"] += 1

        # 1-day: fire once when 0–1 days remain
        if days <= 1 and not tenant.trial_reminder_1d_at:
            if send_trial_reminder_email(tenant, days_left=max(days, 1), usage=usage):
                tenant.trial_reminder_1d_at = now
                stats["one_day"] += 1

    if stats["seven_day"] or stats["one_day"]:
        db.session.commit()
    return stats
