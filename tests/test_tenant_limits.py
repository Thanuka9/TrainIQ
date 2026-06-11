from datetime import datetime, timedelta

from utils.tenant_limits import tenant_is_active, can_tenant_add_user, get_tenant_limits


class _Tenant:
    plan = "trial"
    status = "trial"
    max_users = 10
    id = 1
    trial_ends_at = None


def test_tenant_is_active():
    t = _Tenant()
    t.trial_ends_at = datetime.utcnow() + timedelta(days=10)
    assert tenant_is_active(t)
    t = _Tenant()
    t.status = "suspended"
    assert not tenant_is_active(t)


def test_can_tenant_add_user_limits(monkeypatch):
    t = _Tenant()
    t.trial_ends_at = datetime.utcnow() + timedelta(days=10)

    def fake_count(_tid):
        return 10

    monkeypatch.setattr("utils.tenant_limits.tenant_user_count", fake_count)
    ok, msg = can_tenant_add_user(t)
    assert not ok
    assert "limit" in msg.lower()
