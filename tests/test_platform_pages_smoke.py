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


def test_platform_operations_page(platform_staff_client):
    resp = platform_staff_client.get("/platform/operations")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "Platform Operations" in html
    assert "PostgreSQL" in html
    assert "MongoDB" in html
    assert "LearnIQ" in html or "AI" in html


def test_platform_operations_tabs(platform_staff_client):
    for tab in ("postgres", "mongo", "ai", "integrations"):
        resp = platform_staff_client.get(f"/platform/operations?tab={tab}")
        assert resp.status_code == 200


def test_dashboard_shows_platform_return_nav(platform_staff_client):
    resp = platform_staff_client.get("/dashboard")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "Platform Command Center" in html
    assert "TrainIQ Platform" in html


def test_admin_page_shows_platform_return_nav(platform_staff_client):
    resp = platform_staff_client.get("/admin/admin")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "Platform Command Center" in html
    assert "TrainIQ Platform" in html


def test_error_pages_show_platform_link(platform_staff_client):
    for path in ("/this-route-does-not-exist-xyz",):
        resp = platform_staff_client.get(path)
        assert resp.status_code == 404
        assert "Platform Command Center" in resp.get_data(as_text=True)


def test_platform_topbar_hidden_on_platform_dashboard(platform_staff_client):
    resp = platform_staff_client.get("/platform")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "Platform Command Center" in html
    assert 'platform-topbar-label">Platform</span>' not in html
