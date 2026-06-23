"""Tests for trial reminder emails and feature comparison matrix."""
from datetime import datetime, timedelta
from unittest.mock import patch
import uuid

from utils.billing_plans import FEATURE_COMPARISON, get_feature_comparison


def _make_admin_user(tenant_id: int, email: str):
    from models import User

    return User(
        first_name="A",
        last_name="B",
        employee_email=email,
        employee_id=f"T-{uuid.uuid4().hex[:8].upper()}",
        join_date=datetime.utcnow().date(),
        tenant_id=tenant_id,
        is_super_admin=True,
        is_verified=True,
    )


def test_feature_comparison_has_all_tiers():
    data = get_feature_comparison()
    col_ids = [c["id"] for c in data["columns"]]
    assert col_ids == ["starter", "growth", "business", "enterprise"]
    assert len(data["rows"]) == len(FEATURE_COMPARISON)
    for row in data["rows"]:
        for pid in col_ids:
            assert pid in row


def test_process_trial_reminder_sends_7d_once(app):
    from extensions import db
    from models import Tenant, User
    from utils.billing_plans import apply_trial_to_tenant
    from utils.trial_reminders import process_trial_reminder_emails

    with app.app_context():
        tenant = Tenant(name="Reminder Co", office_key=f"REM{uuid.uuid4().hex[:6].upper()}", allowed_domain="remind.com")
        apply_trial_to_tenant(tenant)
        tenant.trial_ends_at = datetime.utcnow() + timedelta(days=6)
        db.session.add(tenant)
        db.session.flush()
        admin = _make_admin_user(tenant.id, f"admin-{uuid.uuid4().hex[:6]}@remind.com")
        admin.set_password("TestPass123!")
        db.session.add(admin)
        db.session.commit()
        tenant_id = tenant.id
        db.session.expunge_all()

        sent_ids = []

        def _track_send(tenant, **kwargs):
            sent_ids.append(tenant.id)
            return True

        with patch("utils.billing_plans.backfill_missing_trial_dates", return_value=0):
            with patch("utils.trial_reminders.send_trial_reminder_email", side_effect=_track_send):
                stats = process_trial_reminder_emails()
                tenant = Tenant.query.get(tenant_id)
                assert tenant.trial_reminder_7d_at is not None
                assert tenant_id in sent_ids
                assert stats["seven_day"] >= 1

                sent_ids.clear()
                process_trial_reminder_emails()
                tenant = Tenant.query.get(tenant_id)
                assert tenant.trial_reminder_7d_at is not None
                assert tenant_id not in sent_ids

        tenant = Tenant.query.get(tenant_id)
        admin = User.query.filter_by(tenant_id=tenant_id, is_super_admin=True).first()
        if admin:
            db.session.delete(admin)
        if tenant:
            db.session.delete(tenant)
        db.session.commit()


def test_process_trial_reminder_sends_1d(app):
    from extensions import db
    from models import Tenant, User
    from utils.billing_plans import apply_trial_to_tenant
    from utils.trial_reminders import process_trial_reminder_emails

    with app.app_context():
        tenant = Tenant(name="Final Co", office_key=f"FIN{uuid.uuid4().hex[:6].upper()}", allowed_domain="final.com")
        apply_trial_to_tenant(tenant)
        tenant.trial_ends_at = datetime.utcnow() + timedelta(hours=18)
        db.session.add(tenant)
        db.session.flush()
        admin = _make_admin_user(tenant.id, f"admin-{uuid.uuid4().hex[:6]}@final.com")
        admin.set_password("TestPass123!")
        db.session.add(admin)
        db.session.commit()
        tenant_id = tenant.id
        db.session.expunge_all()

        with patch("utils.billing_plans.backfill_missing_trial_dates", return_value=0):
            with patch("utils.trial_reminders.send_trial_reminder_email", return_value=True):
                stats = process_trial_reminder_emails()
                tenant = Tenant.query.get(tenant_id)
                assert tenant.trial_reminder_1d_at is not None
                assert stats["one_day"] >= 1

        tenant = Tenant.query.get(tenant_id)
        admin = User.query.filter_by(tenant_id=tenant_id, is_super_admin=True).first()
        if admin:
            db.session.delete(admin)
        if tenant:
            db.session.delete(tenant)
        db.session.commit()
