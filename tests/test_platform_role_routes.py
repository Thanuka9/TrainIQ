"""Route-level permission checks for platform staff roles (no DB skips)."""
import os

os.environ.setdefault('REDIS_URI', 'memory://')

from unittest.mock import MagicMock, patch

import pytest

_mongo_patcher = patch(
    'mongodb_operations.initialize_mongodb',
    return_value=(MagicMock(), MagicMock()),
)
_setup_patcher = patch('mongodb_operations.setup_collections')
_mongo_patcher.start()
_setup_patcher.start()

from app import app as flask_app  # noqa: E402

_mongo_patcher.stop()
_setup_patcher.stop()


@pytest.fixture
def client():
    flask_app.config['TESTING'] = True
    flask_app.config['WTF_CSRF_ENABLED'] = False
    for lim in flask_app.extensions.get('limiter') or ():
        lim.enabled = True
        lim.enabled = False
    return flask_app.test_client()


def _login_staff(client, user, monkeypatch):
    monkeypatch.setattr('utils.platform_ceo.is_platform_ceo', lambda u=None: False)
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True
        sess['tenant_id'] = user.tenant_id


# ── Support role ───────────────────────────────────────────────


def test_support_blocked_from_revenue(client, support_staff_user, monkeypatch):
    _login_staff(client, support_staff_user, monkeypatch)
    resp = client.get('/platform/revenue', follow_redirects=False)
    assert resp.status_code == 302


def test_support_blocked_from_operations(client, support_staff_user, monkeypatch):
    _login_staff(client, support_staff_user, monkeypatch)
    resp = client.get('/platform/operations', follow_redirects=False)
    assert resp.status_code == 302


def test_support_blocked_from_security(client, support_staff_user, monkeypatch):
    _login_staff(client, support_staff_user, monkeypatch)
    resp = client.get('/platform/security', follow_redirects=False)
    assert resp.status_code == 302


def test_support_blocked_from_activity(client, support_staff_user, monkeypatch):
    _login_staff(client, support_staff_user, monkeypatch)
    resp = client.get('/platform/activity', follow_redirects=False)
    assert resp.status_code == 302


def test_support_blocked_from_tenant_export(client, support_staff_user, monkeypatch):
    _login_staff(client, support_staff_user, monkeypatch)
    resp = client.get('/platform/export/tenants.csv', follow_redirects=False)
    assert resp.status_code == 302


def test_support_blocked_from_staff_invite(client, support_staff_user, monkeypatch):
    _login_staff(client, support_staff_user, monkeypatch)
    resp = client.post(
        '/platform/staff/invite',
        data={'email': 'new@trainiq.com', 'role': 'support'},
        follow_redirects=False,
    )
    assert resp.status_code == 302


def test_support_can_view_users(client, support_staff_user, monkeypatch):
    _login_staff(client, support_staff_user, monkeypatch)
    resp = client.get('/platform/users')
    assert resp.status_code == 200


def test_support_can_view_dashboard(client, support_staff_user, monkeypatch):
    _login_staff(client, support_staff_user, monkeypatch)
    resp = client.get('/platform/dashboard')
    assert resp.status_code == 200


def test_support_can_view_tenants(client, support_staff_user, monkeypatch):
    _login_staff(client, support_staff_user, monkeypatch)
    resp = client.get('/platform/tenants')
    assert resp.status_code == 200


def test_support_can_view_support_queue(client, support_staff_user, monkeypatch):
    _login_staff(client, support_staff_user, monkeypatch)
    resp = client.get('/platform/support')
    assert resp.status_code == 200


def test_support_can_view_staff_hub(client, support_staff_user, monkeypatch):
    _login_staff(client, support_staff_user, monkeypatch)
    resp = client.get('/platform/staff')
    assert resp.status_code == 200


# ── Ops role ───────────────────────────────────────────────────


def test_ops_can_view_activity(client, platform_staff_factory, monkeypatch):
    user = platform_staff_factory('ops')
    _login_staff(client, user, monkeypatch)
    resp = client.get('/platform/activity')
    assert resp.status_code == 200


def test_ops_blocked_from_revenue(client, platform_staff_factory, monkeypatch):
    user = platform_staff_factory('ops')
    _login_staff(client, user, monkeypatch)
    resp = client.get('/platform/revenue', follow_redirects=False)
    assert resp.status_code == 302


def test_ops_blocked_from_operations(client, platform_staff_factory, monkeypatch):
    user = platform_staff_factory('ops')
    _login_staff(client, user, monkeypatch)
    resp = client.get('/platform/operations', follow_redirects=False)
    assert resp.status_code == 302


def test_ops_blocked_from_security(client, platform_staff_factory, monkeypatch):
    user = platform_staff_factory('ops')
    _login_staff(client, user, monkeypatch)
    resp = client.get('/platform/security', follow_redirects=False)
    assert resp.status_code == 302


# ── Admin role ─────────────────────────────────────────────────


def test_admin_can_view_revenue(client, platform_staff_factory, monkeypatch):
    user = platform_staff_factory('admin')
    _login_staff(client, user, monkeypatch)
    resp = client.get('/platform/revenue')
    assert resp.status_code == 200


def test_admin_can_view_security(client, platform_staff_factory, monkeypatch):
    user = platform_staff_factory('admin')
    _login_staff(client, user, monkeypatch)
    resp = client.get('/platform/security')
    assert resp.status_code == 200


def test_admin_blocked_from_operations(client, platform_staff_factory, monkeypatch):
    user = platform_staff_factory('admin')
    _login_staff(client, user, monkeypatch)
    resp = client.get('/platform/operations', follow_redirects=False)
    assert resp.status_code == 302
