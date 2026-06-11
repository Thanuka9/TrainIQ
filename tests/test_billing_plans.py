"""Tests for SaaS billing plans and user limits."""
from datetime import datetime, timedelta

from utils.billing_plans import (
    PLANS,
    apply_paid_plan,
    apply_trial_to_tenant,
    get_plan,
    is_trial_expired,
    tenant_usage,
)
from utils.tenant_limits import can_tenant_add_user, tenant_is_active


class _Tenant:
    id = 1
    plan = "trial"
    status = "trial"
    max_users = 10
    max_storage_mb = 2048
    trial_ends_at = None


def test_trial_plan_defaults():
    plan = get_plan("trial")
    assert plan["max_users"] == 10
    assert plan["trial_days"] == 30


def test_apply_trial_sets_expiry():
    t = _Tenant()
    apply_trial_to_tenant(t)
    assert t.plan == "trial"
    assert t.status == "trial"
    assert t.max_users == 10
    assert t.trial_ends_at is not None
    assert t.trial_ends_at > datetime.utcnow()


def test_apply_paid_plan_upgrades_limits(app):
    with app.app_context():
        t = _Tenant()
        apply_trial_to_tenant(t)
        ok, _ = apply_paid_plan(t, "growth")
        assert ok
        assert t.plan == "growth"
        assert t.status == "active"
        assert t.max_users == PLANS["growth"]["max_users"]
        assert t.trial_ends_at is None


def test_cannot_downgrade_below_user_count(monkeypatch):
    t = _Tenant()
    apply_trial_to_tenant(t)
    monkeypatch.setattr("utils.tenant_limits.tenant_user_count", lambda _tid: 25)
    ok, msg = apply_paid_plan(t, "starter")
    assert not ok
    assert "25" in msg


def test_trial_expired_blocks_active(monkeypatch):
    t = _Tenant()
    apply_trial_to_tenant(t)
    t.trial_ends_at = datetime.utcnow() - timedelta(days=1)
    assert is_trial_expired(t)
    assert not tenant_is_active(t)


def test_backfill_missing_trial_dates(app):
    import uuid
    from extensions import db
    from models import Tenant
    from utils.billing_plans import backfill_missing_trial_dates

    with app.app_context():
        key = f"LEG{uuid.uuid4().hex[:6].upper()}"
        t = Tenant(name="Legacy", office_key=key, allowed_domain="legacy.com", plan="trial", status="trial")
        db.session.add(t)
        db.session.commit()
        assert t.trial_ends_at is None
        count = backfill_missing_trial_dates()
        assert count >= 1
        db.session.refresh(t)
        assert t.trial_ends_at is not None


def test_user_limit_message(monkeypatch):
    t = _Tenant()
    apply_trial_to_tenant(t)
    monkeypatch.setattr("utils.tenant_limits.tenant_user_count", lambda _tid: 10)
    ok, msg = can_tenant_add_user(t)
    assert not ok
    assert "upgrade" in msg.lower()
