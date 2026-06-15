"""TrainIQ platform staff access and invite helpers."""
from __future__ import annotations

import logging
import os
import secrets
import uuid
from datetime import datetime, timedelta

from flask import render_template, url_for
from flask_mail import Message

logger = logging.getLogger(__name__)

STAFF_ROLES = ("support", "ops", "admin")
INVITE_TTL_DAYS = int(os.getenv("PLATFORM_STAFF_INVITE_TTL_DAYS", "7"))


def normalize_email(email: str) -> str:
    return (email or "").strip().lower()


def find_user_by_email(email: str):
    from extensions import db
    from models import User

    normalized = normalize_email(email)
    if not normalized:
        return None
    return User.query.filter(db.func.lower(User.employee_email) == normalized).first()


def user_on_platform_tenant(user) -> bool:
    from utils.tenant_utils import is_platform_tenant

    org = getattr(user, "tenant", None)
    return bool(org and is_platform_tenant(org))


def get_platform_tenant():
    from models import Tenant
    from utils.platform_ceo import TRAINIQ_PLATFORM_OFFICE_KEY

    return Tenant.query.filter_by(office_key=TRAINIQ_PLATFORM_OFFICE_KEY).first()


def list_platform_staff():
    from models import User

    tenant = get_platform_tenant()
    if not tenant:
        return []
    return (
        User.query.filter_by(tenant_id=tenant.id, is_platform_staff=True)
        .order_by(User.first_name, User.last_name)
        .all()
    )


def list_pending_staff_invites():
    from models import PlatformStaffInvite

    return (
        PlatformStaffInvite.query.filter_by(status="pending")
        .order_by(PlatformStaffInvite.created_at.desc())
        .all()
    )


def create_staff_invite(email: str, first_name: str, last_name: str, role: str, invited_by_user_id: int):
    from extensions import db
    from models import PlatformStaffInvite

    email = normalize_email(email)
    role = role if role in STAFF_ROLES else "support"
    token = secrets.token_urlsafe(32)
    invite = PlatformStaffInvite(
        email=email,
        first_name=(first_name or "").strip(),
        last_name=(last_name or "").strip(),
        role=role,
        token=token,
        invited_by_user_id=invited_by_user_id,
        expires_at=datetime.utcnow() + timedelta(days=INVITE_TTL_DAYS),
        status="pending",
    )
    db.session.add(invite)
    db.session.commit()
    return invite


def get_valid_staff_invite(token: str):
    from models import PlatformStaffInvite

    invite = PlatformStaffInvite.query.filter_by(token=(token or "").strip()).first()
    if not invite or not invite.is_valid:
        return None
    return invite


def revoke_staff_invite(invite_id: int) -> bool:
    from extensions import db
    from models import PlatformStaffInvite

    invite = PlatformStaffInvite.query.get(invite_id)
    if not invite or invite.status != "pending":
        return False
    invite.status = "revoked"
    db.session.commit()
    return True


def send_staff_invite_email(invite, mail):
    accept_url = url_for(
        "auth_routes.accept_staff_invite",
        token=invite.token,
        _external=True,
    )
    msg = Message(
        subject="You're invited to join the TrainIQ platform team",
        recipients=[invite.email],
    )
    msg.body = (
        f"Hi {invite.first_name},\n\n"
        f"You have been invited to join the TrainIQ platform operations team.\n\n"
        f"Accept your invitation and set your password:\n{accept_url}\n\n"
        f"This link expires in {INVITE_TTL_DAYS} days."
    )
    msg.html = render_template(
        "emails/platform_staff_invite_email.html",
        invite=invite,
        accept_url=accept_url,
        ttl_days=INVITE_TTL_DAYS,
    )
    mail.send(msg)
    logger.info("Platform staff invite email sent to %s", invite.email)


def activate_staff_from_invite(invite, password: str):
    """Create or update platform staff user from a valid invite."""
    from extensions import db
    from models import Role, User

    tenant = get_platform_tenant()
    if not tenant:
        raise ValueError("Platform tenant not found")

    user = find_user_by_email(invite.email)
    if user:
        user.first_name = invite.first_name
        user.last_name = invite.last_name
        user.tenant_id = tenant.id
        user.is_verified = True
        user.verification_token = None
        user.is_platform_staff = True
        user.platform_staff_role = invite.role
        user.set_password(password)
    else:
        user = User(
            first_name=invite.first_name,
            last_name=invite.last_name,
            employee_email=invite.email,
            employee_id=f"STF-{uuid.uuid4().hex[:6].upper()}",
            join_date=datetime.utcnow().date(),
            is_verified=True,
            is_platform_staff=True,
            platform_staff_role=invite.role,
            tenant_id=tenant.id,
        )
        user.set_password(password)
        db.session.add(user)

    for role_name in ("member", "admin"):
        role = Role.query.filter_by(name=role_name).first()
        if role and role not in user.roles:
            user.roles.append(role)

    invite.status = "accepted"
    invite.accepted_at = datetime.utcnow()
    db.session.commit()
    return user
