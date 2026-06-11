"""Smoke tests for admin analytics and audit log pages."""
import os
os.environ["REDIS_URI"] = "memory://"

from unittest.mock import MagicMock, patch

import pytest

# Patch MongoDB before app module loads (once per session)
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
def admin_client():
    flask_app.config["TESTING"] = True
    flask_app.config["WTF_CSRF_ENABLED"] = False
    for lim in flask_app.extensions.get("limiter") or ():
        lim.enabled = False
    from models import User

    with flask_app.app_context():
        admin = User.query.filter_by(is_super_admin=True).first() or User.query.first()
        if not admin:
            pytest.skip("No users in database")

    client = flask_app.test_client()
    with client.session_transaction() as sess:
        sess["_user_id"] = str(admin.id)
        sess["_fresh"] = True
    return client


def test_analytics_page_renders_new_ui(admin_client):
    resp = admin_client.get("/admin/admin/analytics")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "analytics-hero" in html
    assert "Platform Insights" in html
    assert "analytics-insight-strip" in html
    assert "AnalyticsIQ Insights" in html
    assert "exportAnalyticsPdf" in html
    assert "Avg Exam Scores by Course" in html


def test_audit_logs_page_renders_new_ui(admin_client):
    resp = admin_client.get("/admin/admin/audit-logs")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "Matching Events" in html
    assert "Security Alerts" in html
    assert "auditEventChart" in html
    assert 'name="event_type"' in html
    assert "All types" in html


def test_audit_event_type_filter_param(admin_client):
    resp = admin_client.get("/admin/admin/audit-logs?event_type=FAILED_LOGIN")
    assert resp.status_code == 200


def test_analytics_pdf_export(admin_client):
    resp = admin_client.post(
        "/admin/admin/analytics/export-pdf",
        json={"kpis": {"total_users": 1}, "filters": {}, "insights": "Test", "charts": []},
    )
    assert resp.status_code in (200, 503)
    if resp.status_code == 200:
        assert resp.mimetype == "application/pdf"
