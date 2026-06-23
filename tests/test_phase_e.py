"""Phase E — storage quotas, Stripe reconcile, tenant export."""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest


def test_check_storage_quota_allows_under_limit():
    from utils.tenant_storage import check_storage_quota

    tenant = SimpleNamespace(id=1, plan='starter', max_storage_mb=100, status='active')
    with patch('utils.tenant_storage.get_tenant_storage_usage', return_value={
        'used_bytes': 10 * 1024 * 1024,
        'max_bytes': 100 * 1024 * 1024,
        'used_mb': 10,
    }):
        ok, msg = check_storage_quota(tenant, 1024)
    assert ok is True
    assert msg == ''


def test_check_storage_quota_blocks_over_limit():
    from utils.tenant_storage import check_storage_quota

    tenant = SimpleNamespace(id=1, plan='starter', max_storage_mb=10, status='active')
    with patch('utils.tenant_storage.get_tenant_storage_usage', return_value={
        'used_bytes': 9 * 1024 * 1024,
        'max_bytes': 10 * 1024 * 1024,
        'used_mb': 9,
    }):
        ok, msg = check_storage_quota(tenant, 2 * 1024 * 1024)
    assert ok is False
    assert 'Storage limit' in msg


def test_sum_upload_file_sizes():
    from utils.tenant_storage import sum_upload_file_sizes

    f = MagicMock()
    f.filename = 'doc.pdf'
    f.tell.return_value = 0
    f.read.return_value = b'hello world'
    assert sum_upload_file_sizes([f]) == 11


def test_reconcile_unavailable_without_stripe():
    from utils.billing_reconcile import reconcile_stripe_tenants

    with patch('utils.stripe_billing.stripe_available', return_value=False):
        result = reconcile_stripe_tenants()
    assert result['available'] is False


def test_expected_db_status_mapping():
    from utils.billing_reconcile import _expected_db_status

    assert _expected_db_status('past_due') == 'past_due'
    assert _expected_db_status('active') == 'active'
    assert _expected_db_status('canceled') == 'expired'


def test_tenant_usage_includes_storage(app):
    from utils.billing_plans import tenant_usage
    from models import Tenant

    with app.app_context():
        tenant = Tenant.query.first()
        if not tenant:
            pytest.skip('No tenant')
        with patch('utils.tenant_storage.get_tenant_storage_usage', return_value={
            'used_mb': 12.5,
            'max_storage_mb': 2048,
            'usage_percent': 1,
            'at_limit': False,
        }):
            usage = tenant_usage(tenant)
        assert 'storage_used_mb' in usage
        assert usage['storage_used_mb'] == 12.5


def test_build_tenant_export(app):
    from models import Tenant
    from utils.tenant_export import build_tenant_export

    with app.app_context():
        tenant = Tenant.query.first()
        if not tenant:
            pytest.skip('No tenant')
        payload = build_tenant_export(tenant.id)
        assert payload is not None
        assert payload['tenant']['id'] == tenant.id
        assert 'users' in payload
        assert 'exported_at' in payload


def test_export_routes_registered(app):
    rules = {rule.rule for rule in app.url_map.iter_rules()}
    assert '/admin/billing/export-data.json' in rules
    assert '/platform/revenue/reconcile' in rules
