"""Platform staff access, invites, and login restrictions."""
import os

os.environ["REDIS_URI"] = "memory://"

from unittest.mock import MagicMock, patch

import pytest

_mongo_patcher = patch(
    "mongodb_operations.initialize_mongodb",
    return_value=(MagicMock(), MagicMock()),
)
_setup_patcher = patch("mongodb_operations.setup_collections")
_mongo_patcher.start()
_setup_patcher.start()

from app import app as flask_app  # noqa: E402
from extensions import db  # noqa: E402

_mongo_patcher.stop()
_setup_patcher.stop()


class _FakeTenant:
    def __init__(self, office_key="TRAINIQ"):
        self.office_key = office_key


class _FakeUser:
    is_authenticated = True

    def __init__(
        self,
        email,
        *,
        is_platform_staff=False,
        platform_staff_role=None,
        tenant=None,
        is_super_admin=False,
    ):
        self.employee_email = email
        self.is_platform_staff = is_platform_staff
        self.platform_staff_role = platform_staff_role
        self.tenant = tenant
        self.is_super_admin = is_super_admin


def test_is_trainiq_staff_requires_invite_not_domain():
    from utils.tenant_utils import is_trainiq_staff

    assert not is_trainiq_staff(_FakeUser("ops@trainiq.com"))
    assert not is_trainiq_staff(
        _FakeUser(
            "admin@trainiq.com",
            is_super_admin=True,
            tenant=_FakeTenant("TRAINIQ"),
        )
    )


def test_is_trainiq_staff_invited_on_platform_tenant():
    from utils.tenant_utils import is_trainiq_staff

    user = _FakeUser(
        "ops@example.com",
        is_platform_staff=True,
        platform_staff_role="support",
        tenant=_FakeTenant("TRAINIQ"),
    )
    assert is_trainiq_staff(user)


def test_is_trainiq_staff_ceo_always_allowed():
    from utils.platform_ceo import PLATFORM_CEO_EMAIL
    from utils.tenant_utils import is_trainiq_staff

    assert is_trainiq_staff(_FakeUser(PLATFORM_CEO_EMAIL))


def test_platform_tenant_login_rejects_non_staff(client):
    from models import Tenant, User
    from utils.platform_ceo import TRAINIQ_PLATFORM_OFFICE_KEY

    with flask_app.app_context():
        tenant = Tenant.query.filter_by(office_key=TRAINIQ_PLATFORM_OFFICE_KEY).first()
        if not tenant:
            pytest.skip("Platform tenant not in database")
        user = (
            User.query.filter(User.tenant_id != tenant.id)
            .filter(User.is_platform_staff.is_(False))
            .first()
        )
        if not user:
            pytest.skip("No non-staff user available for login test")
        user.set_password("TestPass1!")
        db.session.commit()
        email = user.employee_email

    resp = client.post(
        "/auth/login",
        data={
            "office_key": TRAINIQ_PLATFORM_OFFICE_KEY,
            "employee_email": email,
            "password": "TestPass1!",
        },
        follow_redirects=True,
    )
    html = resp.get_data(as_text=True)
    assert "staff only" in html.lower() or "organization" in html.lower()


def test_ceo_can_invite_platform_staff(platform_staff_client):
    import uuid

    email = f"newstaff-{uuid.uuid4().hex[:8]}@example.com"
    with patch("utils.platform_staff.send_staff_invite_email") as mock_send:
        resp = platform_staff_client.post(
            "/platform/staff/invite",
            data={
                "email": email,
                "first_name": "New",
                "last_name": "Staff",
                "role": "support",
            },
            follow_redirects=True,
        )
    assert resp.status_code == 200
    mock_send.assert_called_once()
    from models import PlatformStaffInvite

    with flask_app.app_context():
        invite = PlatformStaffInvite.query.filter_by(email=email).first()
        assert invite is not None
        assert invite.status == "pending"
        invite.status = "revoked"
        db.session.commit()


@pytest.fixture
def platform_staff_client():
    flask_app.config["TESTING"] = True
    flask_app.config["WTF_CSRF_ENABLED"] = False
    for lim in flask_app.extensions.get("limiter") or ():
        lim.enabled = False

    from models import User
    from utils.platform_ceo import PLATFORM_CEO_EMAIL

    with flask_app.app_context():
        user = User.query.filter(
            User.employee_email.ilike(PLATFORM_CEO_EMAIL)
        ).first()
        if not user:
            pytest.skip("Platform CEO user not in database")

    client = flask_app.test_client()
    with client.session_transaction() as sess:
        sess["_user_id"] = str(user.id)
        sess["_fresh"] = True
        sess["tenant_id"] = user.tenant_id
    return client


def test_platform_staff_page_renders(platform_staff_client):
    resp = platform_staff_client.get("/platform/staff")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "Platform Staff" in html or "Staff Hub" in html
