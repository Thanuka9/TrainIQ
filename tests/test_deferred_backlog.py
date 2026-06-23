"""Tests for deferred backlog quick wins."""
from unittest.mock import patch

import pytest


def test_db_health_legacy_redirects_to_operations(client, monkeypatch):
    from models import User
    from utils.platform_ceo import PLATFORM_CEO_EMAIL

    monkeypatch.setattr('utils.platform_ip_allowlist.enforce_platform_ip_allowlist', lambda: None)

    with client.application.app_context():
        user = User.query.filter(User.employee_email.ilike(PLATFORM_CEO_EMAIL)).first()
        if not user:
            pytest.skip('Platform CEO user not in database')

    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True
        sess['tenant_id'] = user.tenant_id

    resp = client.get('/platform/db-health?tab=mongo', follow_redirects=False)
    assert resp.status_code == 302
    assert '/platform/operations' in resp.location
    assert 'tab=mongo' in resp.location


def test_platform_ip_allowlist_blocks_when_configured(app, client, monkeypatch):
    from models import User
    from utils.platform_ceo import PLATFORM_CEO_EMAIL

    monkeypatch.setenv('TRAINIQ_PLATFORM_IP_ALLOWLIST', '10.0.0.1')

    with app.app_context():
        user = User.query.filter(User.employee_email.ilike(PLATFORM_CEO_EMAIL)).first()
        if not user:
            pytest.skip('Platform CEO user not in database')

    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True
        sess['tenant_id'] = user.tenant_id

    with patch('utils.platform_ip_allowlist.client_ip', return_value='203.0.113.9'):
        resp = client.get('/platform/dashboard', follow_redirects=False)
    assert resp.status_code == 302
    assert 'dashboard' in resp.location.lower()


def test_platform_ip_allowlist_allows_listed_ip(app, client, monkeypatch):
    from models import User
    from utils.platform_ceo import PLATFORM_CEO_EMAIL

    monkeypatch.setenv('TRAINIQ_PLATFORM_IP_ALLOWLIST', '203.0.113.9')

    with app.app_context():
        user = User.query.filter(User.employee_email.ilike(PLATFORM_CEO_EMAIL)).first()
        if not user:
            pytest.skip('Platform CEO user not in database')

    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True
        sess['tenant_id'] = user.tenant_id

    with patch('utils.platform_ip_allowlist.client_ip', return_value='203.0.113.9'):
        resp = client.get('/platform/dashboard')
    assert resp.status_code == 200


def test_ops_status_for_tab_mongo_skips_postgres_page(monkeypatch):
    monkeypatch.setenv('OPS_CACHE_USE_REDIS', 'false')

    with patch('utils.db_maintenance.load_db_health_page_data') as page_mock:
        with patch(
            'utils.mongo_platform.collect_mongo_ops_status',
            return_value={'available': True, 'status': 'healthy'},
        ):
            from utils.platform_ops import get_platform_ops_status_for_tab

            result = get_platform_ops_status_for_tab('mongo', cache_seconds=0)
    page_mock.assert_not_called()
    assert result['mongo']['available'] is True


def test_staff_manage_permission_ceo_only():
    from utils.platform_staff_permissions import staff_has_permission

    class _U:
        is_authenticated = True
        is_platform_staff = True
        platform_staff_role = 'admin'
        employee_email = 'admin@trainiq.com'

    assert staff_has_permission(_U(), 'staff.manage') is False
    assert staff_has_permission(_U(), 'operations.view') is False
