"""Smoke tests for platform operator pages."""
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

_mongo_patcher.stop()
_setup_patcher.stop()


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


def test_platform_security_page(platform_staff_client):
    resp = platform_staff_client.get("/platform/security")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "Security" in html or "security" in html.lower()


def test_platform_support_page(platform_staff_client):
    resp = platform_staff_client.get("/platform/support")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "Support" in html or "support" in html.lower()
