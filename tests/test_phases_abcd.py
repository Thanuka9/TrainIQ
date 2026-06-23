"""Tests for Phases A–D (security, revenue, observability, DDL)."""
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest


def test_user_requires_2fa_platform_staff(monkeypatch):
    monkeypatch.setenv('PLATFORM_STAFF_REQUIRE_2FA', 'true')
    from utils.auth_session import user_requires_2fa

    user = SimpleNamespace(tenant=SimpleNamespace(enable_2fa=False))
    with patch('utils.tenant_utils.is_trainiq_staff', return_value=True):
        assert user_requires_2fa(user) is True


def test_user_requires_2fa_tenant_flag():
    from utils.auth_session import user_requires_2fa

    user = SimpleNamespace(tenant=SimpleNamespace(enable_2fa=True))
    with patch('utils.tenant_utils.is_trainiq_staff', return_value=False):
        assert user_requires_2fa(user) is True


def test_sso_validate_nonce():
    import base64
    import json

    from utils.sso import validate_sso_nonce

    payload = base64.urlsafe_b64encode(json.dumps({'nonce': 'abc123'}).encode()).decode().rstrip('=')
    token = f'header.{payload}.sig'
    assert validate_sso_nonce(token, 'abc123') is True
    assert validate_sso_nonce(token, 'wrong') is False


def test_sso_email_allowed_respects_domain():
    from utils.sso import sso_email_allowed

    tenant = SimpleNamespace(allowed_domain='acme.com')
    assert sso_email_allowed(tenant, 'user@acme.com') is True
    assert sso_email_allowed(tenant, 'user@evil.com') is False


def test_stripe_price_id_from_env(monkeypatch):
    monkeypatch.setenv('STRIPE_PRICE_STARTER_MONTHLY', 'price_123')
    from utils.billing_plans import stripe_price_id

    assert stripe_price_id('starter', 'monthly') == 'price_123'
    assert stripe_price_id('starter', 'yearly') is None


def test_plan_mrr_prefers_stripe_event(app):
    from models import BillingEvent, Tenant
    from extensions import db
    from utils.platform_analytics import _plan_mrr

    with app.app_context():
        tenant = Tenant.query.first()
        if not tenant:
            pytest.skip('No tenant in database')
        tenant.stripe_subscription_id = 'sub_test'
        ev = BillingEvent(
            tenant_id=tenant.id,
            idempotency_key=f'test-mrr-{datetime.utcnow().timestamp()}',
            source='stripe_invoice',
            status='applied',
            plan_id='starter',
            billing_cycle='monthly',
            amount_cents=4900,
            created_at=datetime.utcnow(),
        )
        db.session.add(ev)
        db.session.commit()
        try:
            assert _plan_mrr(tenant) == 49.0
        finally:
            db.session.delete(ev)
            tenant.stripe_subscription_id = None
            db.session.commit()


def test_schema_guards_use_ddl_executor_for_indexes(app, monkeypatch):
    monkeypatch.setenv('SCHEMA_GUARDS_FROZEN', 'false')
    with app.app_context():
        with patch('utils.startup_schema.all_schema_ddl', return_value=['CREATE INDEX IF NOT EXISTS ix_test ON users (id)']):
            with patch('utils.ddl_executor.execute_postgres_ddl') as exec_mock:
                with patch('utils.db_maintenance_lock.platform_maintenance_lock'):
                    from utils.startup_schema import apply_startup_schema_guards

                    apply_startup_schema_guards(force=True)
        exec_mock.assert_called_once()


def test_prometheus_metrics_disabled_by_default():
    from utils.prometheus_metrics import metrics_enabled

    assert metrics_enabled() is False


def test_prometheus_authorize_dev_without_token(monkeypatch):
    monkeypatch.setenv('FLASK_ENV', 'development')
    monkeypatch.delenv('PROMETHEUS_METRICS_TOKEN', raising=False)
    from utils.prometheus_metrics import authorize_metrics_request

    assert authorize_metrics_request(None) is True
