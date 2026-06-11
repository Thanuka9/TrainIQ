"""Tests for organization announcements."""
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
def admin_client():
    flask_app.config["TESTING"] = True
    flask_app.config["WTF_CSRF_ENABLED"] = False
    from models import User

    with flask_app.app_context():
        admin = User.query.filter_by(is_super_admin=True).first()
        if not admin:
            pytest.skip("No super admin")
        tenant_id = admin.tenant_id

    client = flask_app.test_client()
    with client.session_transaction() as sess:
        sess["_user_id"] = str(admin.id)
        sess["_fresh"] = True
        sess["tenant_id"] = tenant_id
        sess["is_super_admin"] = True
    return client, admin


def test_manage_announcements_page(admin_client):
    client, _ = admin_client
    resp = client.get("/admin/admin/announcements")
    assert resp.status_code == 200
    assert "Organization Announcements" in resp.get_data(as_text=True)


def test_create_and_list_announcement(admin_client):
    client, admin = admin_client
    resp = client.post(
        "/admin/admin/announcements/create",
        data={
            "title": "Test Announcement",
            "message": "Hello team",
            "is_pinned": "1",
        },
        follow_redirects=True,
    )
    assert resp.status_code == 200
    from utils.announcements import active_announcements_for_tenant

    with flask_app.app_context():
        items = active_announcements_for_tenant(admin.tenant_id)
        assert any(a["title"] == "Test Announcement" for a in items)
