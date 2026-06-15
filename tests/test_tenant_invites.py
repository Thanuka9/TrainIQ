"""Tests for tenant invite tokens."""
import uuid
from datetime import datetime, timedelta

import pytest

from extensions import db
from models import Tenant, TenantInvite, User
from utils.tenant_invites import create_tenant_invite, get_valid_invite, mark_invite_used, revoke_tenant_invite


@pytest.fixture
def invite_tenant(app):
    with app.app_context():
        tenant = Tenant(
            name="Invite Co",
            allowed_domain="inviteco.com",
            office_key=f"INV{uuid.uuid4().hex[:6].upper()}",
            enable_invite_only=True,
        )
        db.session.add(tenant)
        db.session.commit()
        yield tenant
        TenantInvite.query.filter_by(tenant_id=tenant.id).delete()
        User.query.filter_by(tenant_id=tenant.id).delete()
        db.session.delete(tenant)
        db.session.commit()


def test_create_and_accept_invite_token(app, invite_tenant):
    email = f"newuser-{uuid.uuid4().hex[:8]}@inviteco.com"
    with app.app_context():
        invite = create_tenant_invite(invite_tenant.id, email, invited_by_user_id=None)
        assert invite.token
        assert get_valid_invite(invite.token) is not None

        user = User(
            first_name="New",
            last_name="User",
            employee_email=email,
            employee_id=f"EMP-{uuid.uuid4().hex[:6].upper()}",
            join_date=datetime.utcnow().date(),
            is_verified=True,
            tenant_id=invite_tenant.id,
        )
        user.set_password("Test@1234")
        db.session.add(user)
        db.session.commit()

        mark_invite_used(invite, user.id)
        assert get_valid_invite(invite.token) is None


def test_revoke_pending_invite(app, invite_tenant):
    email = f"revoke-{uuid.uuid4().hex[:8]}@inviteco.com"
    with app.app_context():
        invite = create_tenant_invite(invite_tenant.id, email, invited_by_user_id=None)
        assert revoke_tenant_invite(invite.id, invite_tenant.id) is True
        assert TenantInvite.query.get(invite.id) is None


def test_invite_role_persisted_and_sanitized(app, invite_tenant):
    with app.app_context():
        admin_invite = create_tenant_invite(
            invite_tenant.id,
            f"adm-{uuid.uuid4().hex[:8]}@inviteco.com",
            invited_by_user_id=None,
            role="admin",
        )
        assert admin_invite.role == "admin"

        bogus_invite = create_tenant_invite(
            invite_tenant.id,
            f"bogus-{uuid.uuid4().hex[:8]}@inviteco.com",
            invited_by_user_id=None,
            role="hacker",
        )
        assert bogus_invite.role == "learner"


def test_expired_invite_rejected(app, invite_tenant):
    with app.app_context():
        invite = TenantInvite(
            tenant_id=invite_tenant.id,
            email=f"expired-{uuid.uuid4().hex[:8]}@inviteco.com",
            token=f"expired-{uuid.uuid4().hex}",
            expires_at=datetime.utcnow() - timedelta(days=1),
        )
        db.session.add(invite)
        db.session.commit()
        assert get_valid_invite(invite.token) is None
