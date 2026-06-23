"""Tests for granular admin permissions."""
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
from models import User  # noqa: E402
from utils.admin_permissions import (  # noqa: E402
    apply_preset_for_user,
    compute_overrides_from_desired,
    resolve_permissions,
    user_can_access_route,
    user_has_permission,
)

_mongo_patcher.stop()
_setup_patcher.stop()

for _lim in flask_app.extensions.get("limiter") or ():
    _lim.enabled = False


@pytest.fixture
def app_ctx():
    flask_app.config["TESTING"] = True
    with flask_app.app_context():
        yield flask_app


def test_member_with_analyst_preset_gets_analytics(app_ctx):
    user = User.query.filter_by(is_super_admin=False).first()
    if not user:
        pytest.skip("No users")
    user.is_super_admin = False
    user.admin_permissions = apply_preset_for_user(user, "analyst")
    db.session.commit()

    perms = resolve_permissions(user)
    assert "analytics.view" in perms
    assert "reports.view" in perms
    assert "users.manage" not in perms


def test_custom_grants_add_to_role_base(app_ctx):
    user = User.query.filter_by(is_super_admin=False).first()
    if not user:
        pytest.skip("No users")
    user.admin_permissions = compute_overrides_from_desired(user, ["support.manage"])
    db.session.commit()

    assert user_has_permission(user, "support.manage")
    assert user_can_access_route(user, "admin_list_tickets")
    assert not user_can_access_route(user, "view_users")


def test_super_admin_bypasses_all_routes(app_ctx):
    admin = User.query.filter_by(is_super_admin=True).first()
    if not admin:
        pytest.skip("No super admin")
    assert user_can_access_route(admin, "tenant_settings")
    assert user_can_access_route(admin, "view_courses")


def test_route_denied_without_permission(app_ctx):
    user = User.query.filter_by(is_super_admin=False).first()
    if not user:
        pytest.skip("No users")
    user.is_super_admin = False
    user.admin_permissions = None
    user.roles = []
    db.session.commit()

    assert not user_can_access_route(user, "view_audit_logs")


def test_permissions_page_requires_super_admin(app_ctx):
    flask_app.config["WTF_CSRF_ENABLED"] = False
    user = User.query.filter_by(is_super_admin=False).first()
    if not user:
        pytest.skip("No users")

    client = flask_app.test_client()
    with client.session_transaction() as sess:
        sess["_user_id"] = str(user.id)
        sess["_fresh"] = True

    resp = client.get(f"/admin/admin/user/{user.id}/permissions")
    assert resp.status_code in (302, 403)


def test_user_with_permissions_manage_can_open_access_page(app_ctx):
    from models import Role

    flask_app.config["WTF_CSRF_ENABLED"] = False
    manager = User.query.filter_by(is_super_admin=False).first()
    target = User.query.filter(User.id != manager.id, User.is_super_admin.is_(False), User.tenant_id == manager.tenant_id).first()
    if not manager or not target:
        pytest.skip("Need two non-super users in the same tenant")

    manager.is_super_admin = False
    manager.admin_permissions = {
        "preset": "custom",
        "grants": ["users.permissions", "dashboard"],
        "denies": [],
    }
    db.session.commit()

    client = flask_app.test_client()
    with client.session_transaction() as sess:
        sess["_user_id"] = str(manager.id)
        sess["_fresh"] = True

    resp = client.get(f"/admin/admin/user/{target.id}/permissions")
    assert resp.status_code == 200
    assert b"Admin Access" in resp.data
