"""Tests for missed Phase A–D follow-ups (TOTP, past_due, canonical ops routes)."""
from types import SimpleNamespace
from unittest.mock import patch

import pytest


def test_past_due_blocks_regular_user():
    from utils.billing_status import past_due_login_allowed

    tenant = SimpleNamespace(status='past_due', name='Acme')
    user = SimpleNamespace(is_super_admin=False)
    with patch('utils.billing_status.user_can_access_past_due_org', return_value=False):
        ok, msg = past_due_login_allowed(tenant, user)
    assert ok is False
    assert 'failed payment' in msg.lower()


def test_past_due_allows_billing_admin():
    from utils.billing_status import past_due_login_allowed

    tenant = SimpleNamespace(status='past_due', name='Acme')
    user = SimpleNamespace(is_super_admin=False)
    with patch('utils.billing_status.user_can_access_past_due_org', return_value=True):
        ok, reason = past_due_login_allowed(tenant, user)
    assert ok is True
    assert reason == 'past_due'


def test_totp_verify_roundtrip():
    pytest.importorskip('pyotp')
    from utils.totp_2fa import generate_totp_secret, verify_totp_code

    import pyotp

    secret = generate_totp_secret()
    code = pyotp.TOTP(secret).now()
    assert verify_totp_code(secret, code) is True
    assert verify_totp_code(secret, '000000') is False


def test_platform_oidc_configured(monkeypatch):
    from utils.platform_sso import platform_oidc_configured

    monkeypatch.delenv('PLATFORM_OIDC_CLIENT_ID', raising=False)
    assert platform_oidc_configured() is False

    monkeypatch.setenv('PLATFORM_OIDC_CLIENT_ID', 'cid')
    monkeypatch.setenv('PLATFORM_OIDC_CLIENT_SECRET', 'sec')
    monkeypatch.setenv('PLATFORM_OIDC_ISSUER_URL', 'https://issuer.example')
    assert platform_oidc_configured() is True


def test_metrics_api_payload_includes_billing_observability(app):
    with app.app_context():
        from utils.platform_metrics_api import build_metrics_api_payload

        payload = build_metrics_api_payload()
        assert 'billing' in payload
        assert 'stripe_configured' in payload['billing']
        assert 'observability' in payload
        assert 'prometheus_enabled' in payload['observability']


def test_canonical_operations_endpoints_registered(app):
    endpoint_names = {rule.endpoint for rule in app.url_map.iter_rules()}
    for name in (
        'platform_routes.platform_operations_run',
        'platform_routes.platform_operations_apply_safe',
        'platform_routes.platform_security_totp',
    ):
        assert name in endpoint_names


def test_auth_session_prefers_totp_when_enrolled(app):
    from utils.auth_session import complete_login_or_2fa

    user = SimpleNamespace(
        id=1,
        totp_enabled=True,
        totp_secret='SECRET',
        tenant=SimpleNamespace(enable_2fa=True),
    )
    with app.test_request_context():
        with patch('utils.auth_session.user_requires_2fa', return_value=True):
            with patch('utils.totp_2fa.user_has_totp', return_value=True):
                with patch('utils.auth_session.redirect') as redir:
                    with patch('utils.auth_session.url_for', return_value='/verify_totp'):
                        complete_login_or_2fa(user)
    redir.assert_called_once()
