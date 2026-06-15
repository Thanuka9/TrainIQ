"""Billing duplicate-payment guard tests."""
import uuid
from datetime import datetime, timedelta
from types import SimpleNamespace

from utils.billing_guard import (
    apply_plan_upgrade,
    billing_period_end_for,
    evaluate_upgrade,
    tenant_in_active_paid_period,
    validate_checkout_start,
)


def test_billing_period_end_monthly():
    start = datetime(2026, 6, 1)
    end = billing_period_end_for(start, "monthly")
    assert end == start + timedelta(days=30)


def test_evaluate_upgrade_allows_trial_to_paid():
    tenant = SimpleNamespace(plan="trial", status="trial", billing_cycle="monthly", billing_period_end=None)
    decision = evaluate_upgrade(tenant, "starter", "monthly")
    assert decision["ok"] is True


def test_evaluate_upgrade_blocks_duplicate_same_plan():
    end = datetime.utcnow() + timedelta(days=20)
    tenant = SimpleNamespace(
        plan="starter",
        status="active",
        billing_cycle="monthly",
        billing_period_end=end,
    )
    assert tenant_in_active_paid_period(tenant) is True
    decision = evaluate_upgrade(tenant, "starter", "monthly")
    assert decision["ok"] is False
    assert decision["is_duplicate"] is True


def test_evaluate_upgrade_allows_higher_tier():
    end = datetime.utcnow() + timedelta(days=20)
    tenant = SimpleNamespace(
        plan="starter",
        status="active",
        billing_cycle="monthly",
        billing_period_end=end,
    )
    decision = evaluate_upgrade(tenant, "growth", "monthly")
    assert decision["ok"] is True
    assert decision["is_upgrade"] is True


def test_evaluate_upgrade_blocks_downgrade():
    end = datetime.utcnow() + timedelta(days=20)
    tenant = SimpleNamespace(
        plan="growth",
        status="active",
        billing_cycle="monthly",
        billing_period_end=end,
    )
    decision = evaluate_upgrade(tenant, "starter", "monthly")
    assert decision["ok"] is False
    assert decision["is_downgrade"] is True


def test_validate_checkout_start_blocks_duplicate(app):
    with app.app_context():
        from extensions import db
        from models import Tenant
        from utils.billing_plans import apply_trial_to_tenant

        office_key = f"DUP{uuid.uuid4().hex[:8].upper()}"
        tenant = Tenant(name="Dup Co", office_key=office_key)
        apply_trial_to_tenant(tenant)
        db.session.add(tenant)
        db.session.flush()
        tenant.plan = "starter"
        tenant.status = "active"
        tenant.billing_cycle = "monthly"
        tenant.billing_period_end = datetime.utcnow() + timedelta(days=25)
        db.session.commit()

        ok, msg = validate_checkout_start(tenant, "starter", "monthly")
        assert ok is False
        assert "already on" in msg.lower()

        db.session.delete(tenant)
        db.session.commit()


def test_apply_plan_upgrade_idempotent(app):
    with app.app_context():
        from extensions import db
        from models import BillingEvent, Tenant
        from utils.billing_plans import apply_trial_to_tenant

        office_key = f"IDM{uuid.uuid4().hex[:8].upper()}"
        tenant = Tenant(name="Idem Co", office_key=office_key)
        apply_trial_to_tenant(tenant)
        db.session.add(tenant)
        db.session.commit()

        idem_key = f"test:idem:{uuid.uuid4().hex}"
        ok1, _ = apply_plan_upgrade(
            tenant,
            "starter",
            billing_cycle="monthly",
            source="manual_upgrade",
            idempotency_key=idem_key,
        )
        assert ok1 is True
        db.session.commit()

        ok2, msg2 = apply_plan_upgrade(
            tenant,
            "starter",
            billing_cycle="monthly",
            source="manual_upgrade",
            idempotency_key=idem_key,
        )
        assert ok2 is True
        assert "already processed" in msg2.lower()
        assert BillingEvent.query.filter_by(tenant_id=tenant.id, status="applied").count() == 1

        BillingEvent.query.filter_by(tenant_id=tenant.id).delete()
        db.session.delete(tenant)
        db.session.commit()
