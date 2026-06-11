"""Admin users page action redirect tests."""
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
    for lim in flask_app.extensions.get("limiter") or ():
        lim.enabled = False
    from models import User

    with flask_app.app_context():
        admin = User.query.filter_by(is_super_admin=True).first() or User.query.first()
        if not admin:
            pytest.skip("No users in database")
        tenant_id = admin.tenant_id

    client = flask_app.test_client()
    with client.session_transaction() as sess:
        sess["_user_id"] = str(admin.id)
        sess["_fresh"] = True
        sess["tenant_id"] = tenant_id
        sess["is_super_admin"] = True
    return client, admin


def test_delete_user_redirects_to_users_page(admin_client):
    client, admin = admin_client
    from extensions import db
    from models import User
    import uuid

    with flask_app.app_context():
        victim = User(
            first_name="Del",
            last_name="Test",
            employee_email=f"del-{uuid.uuid4().hex[:8]}@example.com",
            employee_id=f"DEL-{uuid.uuid4().hex[:6]}",
            join_date=admin.join_date,
            is_verified=False,
            tenant_id=admin.tenant_id,
        )
        victim.set_password("TempPass123!")
        db.session.add(victim)
        db.session.commit()
        vid = victim.id

    resp = client.post(
        f"/admin/admin/user/delete/{vid}",
        data={"status": "verified"},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert "/admin/users" in resp.location or "/admin/admin/users" in resp.location
    assert "status=verified" in resp.location

    with flask_app.app_context():
        assert User.query.get(vid) is None


def test_users_page_edit_dept_dropdown_uses_trainiq_pattern(admin_client):
    client, _admin = admin_client
    resp = client.get("/admin/admin/users?status=verified")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert 'data-tiq-dropdown="deptMenu-' in html
    assert 'name="status" value="verified"' in html
