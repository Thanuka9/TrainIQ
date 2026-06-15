"""Stripe billing foundation tests."""
from types import SimpleNamespace
from unittest.mock import patch

from utils.platform_analytics import _plan_mrr
from utils.stripe_billing import create_checkout_session, handle_webhook_payload, stripe_available


def test_stripe_available_without_key(monkeypatch):
    monkeypatch.delenv("STRIPE_SECRET_KEY", raising=False)
    monkeypatch.setattr("utils.stripe_billing.STRIPE_SECRET_KEY", "")
    monkeypatch.setattr("utils.stripe_billing.STRIPE_ENABLED", False)
    assert stripe_available() is False


def test_create_checkout_disabled():
    tenant = SimpleNamespace(id=1, name="Acme", billing_email="a@acme.com", office_key="ACME")
    sid, url = create_checkout_session(
        tenant=tenant,
        plan_id="starter",
        billing_cycle="monthly",
        success_url="http://localhost/s",
        cancel_url="http://localhost/c",
    )
    assert sid is None and url is None


def test_plan_mrr_enterprise_custom_cents():
    tenant = SimpleNamespace(plan="enterprise", billing_cycle="monthly", custom_mrr_cents=125000)
    assert _plan_mrr(tenant) == 1250.0


def test_handle_webhook_without_secret():
    assert handle_webhook_payload(b"{}", "sig") is None


def test_handle_webhook_verifies_event(monkeypatch):
    monkeypatch.setattr("utils.stripe_billing.STRIPE_ENABLED", True)
    monkeypatch.setattr("utils.stripe_billing.STRIPE_WEBHOOK_SECRET", "whsec_test")

    class FakeStripe:
        class Webhook:
            @staticmethod
            def construct_event(payload, sig, secret):
                return {"type": "checkout.session.completed", "data": {"object": {}}}

    monkeypatch.setitem(__import__("sys").modules, "stripe", FakeStripe)
    event = handle_webhook_payload(b"{}", "sig_header")
    assert event["type"] == "checkout.session.completed"
