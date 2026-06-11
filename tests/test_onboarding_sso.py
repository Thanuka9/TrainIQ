"""Tests for trial checklist and onboarding emails."""
from datetime import datetime, timedelta
from unittest.mock import patch

from utils.trial_checklist import INVITE_TARGET, get_trial_checklist


class _TrialTenant:
    id = 99
    plan = "trial"
    status = "trial"
    trial_ends_at = None


def test_trial_checklist_empty_progress():
    t = _TrialTenant()
    t.trial_ends_at = datetime.utcnow() + timedelta(days=20)
    with patch("utils.trial_checklist._has_course", return_value=False), patch(
        "utils.trial_checklist._team_member_count", return_value=0
    ), patch("utils.trial_checklist._has_exam_attempt", return_value=False):
        data = get_trial_checklist(t)
    assert data is not None
    assert data["completed"] == 0
    assert data["total"] == 3
    assert data["steps"][1]["description"] == f"0/{INVITE_TARGET} members added"


def test_trial_checklist_not_for_paid_plan():
    t = _TrialTenant()
    t.plan = "growth"
    assert get_trial_checklist(t) is None


def test_send_welcome_marks_timestamp(app):
    import uuid
    from extensions import db
    from models import Tenant, User
    from utils.onboarding_emails import send_welcome_email

    with app.app_context():
        key = f"WEL{uuid.uuid4().hex[:6].upper()}"
        tenant = Tenant(name="Welcome Co", office_key=key, allowed_domain="wel.com", plan="trial")
        db.session.add(tenant)
        db.session.flush()
        admin = User(
            first_name="A",
            last_name="B",
            employee_email=f"admin-{uuid.uuid4().hex[:6]}@wel.com",
            employee_id=f"E-{uuid.uuid4().hex[:6].upper()}",
            join_date=datetime.utcnow().date(),
            tenant_id=tenant.id,
            is_super_admin=True,
            is_verified=True,
        )
        admin.set_password("TestPass123!")
        db.session.add(admin)
        db.session.commit()

        with patch("extensions.mail.send"):
            with app.test_request_context():
                assert send_welcome_email(tenant, admin_user=admin)
        db.session.refresh(tenant)
        assert tenant.onboarding_welcome_at is not None


def test_tenant_sso_requires_enterprise():
    from utils.sso import tenant_sso_available

    class T:
        sso_enabled = True
        plan = "growth"
        sso_client_id = "x"
        sso_client_secret = "y"
        sso_provider = "google"
        sso_issuer_url = None
        sso_tenant_domain = None

    assert not tenant_sso_available(T())

    T.plan = "enterprise"
    assert tenant_sso_available(T())
