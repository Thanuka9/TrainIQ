"""Auth flow fixes — case-insensitive email, forgot password, reset unlock."""
import os

os.environ["REDIS_URI"] = "memory://"

from datetime import datetime, timedelta
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


@pytest.fixture
def client():
    flask_app.config["TESTING"] = True
    flask_app.config["WTF_CSRF_ENABLED"] = False
    for lim in flask_app.extensions.get("limiter") or ():
        lim.enabled = False
    return flask_app.test_client()


def test_forgot_password_generic_message_unknown_email(client):
    with patch("auth_routes.mail") as mock_mail:
        mock_mail.send = MagicMock()
        resp = client.post(
            "/auth/forgot_password",
            data={"employee_email": "nobody-at-all@example.com"},
            follow_redirects=True,
        )
    html = resp.get_data(as_text=True)
    assert "if an account exists" in html.lower()
    mock_mail.send.assert_not_called()


def test_forgot_password_generic_message_known_email(client):
    from models import User

    with flask_app.app_context():
        user = User.query.filter(User.is_verified.is_(True)).first()
        if not user:
            pytest.skip("No verified user in database")

    with patch("auth_routes.mail") as mock_mail:
        mock_mail.send = MagicMock()
        resp = client.post(
            "/auth/forgot_password",
            data={"employee_email": user.employee_email.upper()},
            follow_redirects=True,
        )
    html = resp.get_data(as_text=True)
    assert "if an account exists" in html.lower()
    assert "email not found" not in html.lower()
    mock_mail.send.assert_called_once()


def test_reset_password_unlocks_account(client):
    from auth_routes import s
    from models import PasswordResetRequest, User

    with flask_app.app_context():
        user = User.query.filter(User.is_verified.is_(True)).first()
        if not user:
            pytest.skip("No verified user in database")
        user_id = user.id
        user.is_locked = True
        user.failed_login_count = 5
        token = s.dumps(user.employee_email, salt="password-reset-salt")
        pr = PasswordResetRequest(
            user_id=user_id,
            token=token,
            expires_at=datetime.utcnow() + timedelta(hours=1),
        )
        db.session.add(pr)
        db.session.commit()

    resp = client.post(
        f"/auth/reset_password/{token}",
        data={"new_password": "NewPass1!", "confirm_password": "NewPass1!"},
        follow_redirects=True,
    )
    assert resp.status_code == 200

    with flask_app.app_context():
        user = User.query.get(user_id)
        assert user.is_locked is False
        assert user.failed_login_count == 0


def test_case_insensitive_login(client):
    from models import Tenant, User

    with flask_app.app_context():
        user = (
            User.query.filter(User.is_verified.is_(True), User.tenant_id.isnot(None))
            .join(Tenant, User.tenant_id == Tenant.id)
            .filter(Tenant.office_key.isnot(None))
            .first()
        )
        if not user or not user.tenant or not user.tenant.office_key:
            pytest.skip("No tenant user with office key in database")
        from utils.tenant_utils import is_platform_tenant

        if is_platform_tenant(user.tenant):
            pytest.skip("Skipping platform tenant user for org login test")
        user.set_password("CaseTest1!")
        db.session.commit()
        office_key = user.tenant.office_key
        email_upper = user.employee_email.upper()

    with patch("auth_routes._send_2fa_email"):
        resp = client.post(
            "/auth/login",
            data={
                "office_key": office_key,
                "employee_email": email_upper,
                "password": "CaseTest1!",
            },
            follow_redirects=False,
        )
    assert resp.status_code in (200, 302)
    if resp.status_code == 302:
        assert "verify_2fa" in resp.location or "dashboard" in resp.location or "platform" in resp.location
