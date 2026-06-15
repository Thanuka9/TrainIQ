"""Platform analytics and dashboard tests."""
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


def test_get_platform_analytics_structure():
    from utils.platform_analytics import get_platform_analytics

    with flask_app.app_context():
        stats = get_platform_analytics()
    for key in (
        "total_tenants",
        "total_users",
        "estimated_mrr",
        "estimated_arr",
        "tenant_rows",
        "by_plan",
        "by_status",
    ):
        assert key in stats


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


def test_platform_dashboard_renders(platform_staff_client):
    resp = platform_staff_client.get("/platform/dashboard")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "Platform Command Center" in html
    assert "Est. MRR" in html
    assert "Courses" in html


def test_platform_users_page(platform_staff_client):
    resp = platform_staff_client.get("/platform/users")
    assert resp.status_code == 200
    assert "Global User Directory" in resp.get_data(as_text=True)


def test_platform_revenue_page(platform_staff_client):
    resp = platform_staff_client.get("/platform/revenue")
    assert resp.status_code == 200
    assert "Revenue" in resp.get_data(as_text=True)


def test_platform_activity_page(platform_staff_client):
    resp = platform_staff_client.get("/platform/activity")
    assert resp.status_code == 200
    assert "Platform Activity" in resp.get_data(as_text=True)


def test_platform_dashboard_denied_for_regular_user():
    flask_app.config["TESTING"] = True
    flask_app.config["WTF_CSRF_ENABLED"] = False
    for lim in flask_app.extensions.get("limiter") or ():
        lim.enabled = False

    from models import User

    with flask_app.app_context():
        user = (
            User.query.filter(User.is_super_admin.is_(False))
            .filter(User.employee_email.notilike("%trainiq.com%"))
            .first()
        )
        if not user:
            pytest.skip("No regular tenant user in database")

    client = flask_app.test_client()
    with client.session_transaction() as sess:
        sess["_user_id"] = str(user.id)
        sess["_fresh"] = True
        sess["tenant_id"] = user.tenant_id

    resp = client.get("/platform/dashboard", follow_redirects=False)
    assert resp.status_code in (302, 303)
    assert "dashboard" in (resp.location or "").lower() or resp.status_code == 302


def test_security_headers_present():
    client = flask_app.test_client()
    resp = client.get("/auth/login")
    assert resp.headers.get("X-Frame-Options") == "DENY"
    assert resp.headers.get("X-Content-Type-Options") == "nosniff"
    assert "Content-Security-Policy" in resp.headers
