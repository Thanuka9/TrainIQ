"""Tenant invite tokens — magic-link registration with 2FA verification."""
from __future__ import annotations

import logging
import secrets
from datetime import datetime, timedelta

from flask import url_for
from flask_mail import Message

logger = logging.getLogger(__name__)

INVITE_TTL_DAYS = int(__import__("os").getenv("INVITE_TOKEN_TTL_DAYS", "7"))


def create_tenant_invite(tenant_id: int, email: str, invited_by_user_id: int):
    from extensions import db
    from models import TenantInvite

    email = (email or "").strip().lower()
    token = secrets.token_urlsafe(32)
    invite = TenantInvite(
        tenant_id=tenant_id,
        email=email,
        token=token,
        invited_by_user_id=invited_by_user_id,
        expires_at=datetime.utcnow() + timedelta(days=INVITE_TTL_DAYS),
    )
    db.session.add(invite)
    db.session.commit()
    return invite


def get_valid_invite(token: str):
    from models import TenantInvite

    invite = TenantInvite.query.filter_by(token=(token or "").strip()).first()
    if not invite or invite.used_at or invite.expires_at <= datetime.utcnow():
        return None
    return invite


def mark_invite_used(invite, user_id: int):
    from extensions import db

    invite.used_at = datetime.utcnow()
    invite.used_by_user_id = user_id
    db.session.commit()


def send_invite_email(invite, tenant, mail, *, external=True):
    from extensions import mail as default_mail

    mail = mail or default_mail
    accept_url = url_for("auth_routes.accept_invite", token=invite.token, _external=external)
    msg = Message(
        subject=f"You're invited to join {tenant.name} on TrainIQ",
        recipients=[invite.email],
    )
    msg.body = (
        f"You have been invited to join {tenant.name} on TrainIQ.\n\n"
        f"Accept your invitation and set your password:\n{accept_url}\n\n"
        f"This link expires in {INVITE_TTL_DAYS} days.\n"
        f"After setting your password, you will receive a 2FA code by email to complete sign-in."
    )
    try:
        from flask import render_template

        msg.html = render_template(
            "emails/invite_email.html",
            tenant=tenant,
            accept_url=accept_url,
            ttl_days=INVITE_TTL_DAYS,
        )
    except Exception:
        pass
    mail.send(msg)
    logger.info("Invite email sent to %s for tenant %s", invite.email, tenant.id)
