"""Phase F — billing history, access review, break-glass, GDPR, nav merge."""
from types import SimpleNamespace
from unittest.mock import patch

import pytest


def test_monthly_revenue_series_empty(app):
    with app.app_context():
        from utils.billing_history import monthly_revenue_series

        assert monthly_revenue_series(months=6) == []


def test_access_review_csv_header(app):
    with app.app_context():
        from utils.access_review_export import access_review_csv

        csv_data = access_review_csv(audit_days=7)
        assert 'record_type' in csv_data.splitlines()[0]
        assert 'staff_account' in csv_data or 'audit_event' in csv_data or csv_data.count('\n') >= 1


def test_anonymize_blocks_platform_tenant(app):
    with app.app_context():
        from utils.tenant_gdpr import anonymize_tenant
        from utils.platform_staff import get_platform_tenant

        tenant = get_platform_tenant()
        if not tenant:
            pytest.skip('No platform tenant')
        ok, msg = anonymize_tenant(tenant)
        assert ok is False
        assert 'platform' in msg.lower()


def test_tenant_is_active_rejects_anonymized():
    from utils.tenant_limits import tenant_is_active

    tenant = SimpleNamespace(status='anonymized', plan='trial', trial_ends_at=None)
    assert tenant_is_active(tenant) is False


def test_schema_guards_frozen_skips_bootstrap_force(monkeypatch):
    monkeypatch.setenv('SCHEMA_GUARDS_FROZEN', 'true')
    from utils.db_platform import _schema_guards_frozen

    assert _schema_guards_frozen() is True


def test_phase_f_routes_registered(app):
    rules = {rule.rule for rule in app.url_map.iter_rules()}
    assert '/platform/export/access-review.csv' in rules
    assert '/platform/tenants/1/anonymize' in rules or any('/anonymize' in r for r in rules)
