"""Security and permission guards for platform CEO / staff routes."""
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from utils.platform_ceo import is_platform_ceo
from utils.platform_staff import validate_staff_target
from utils.platform_staff_permissions import staff_has_permission


class _User:
    is_authenticated = True

    def __init__(self, *, email, tenant_id=1, is_platform_staff=False, platform_staff_role=None):
        self.id = 99
        self.employee_email = email
        self.tenant_id = tenant_id
        self.is_platform_staff = is_platform_staff
        self.platform_staff_role = platform_staff_role
        self.tenant = SimpleNamespace(id=tenant_id, office_key="TRAINIQ")


def test_ceo_role_in_db_does_not_grant_ceo_access(monkeypatch):
    monkeypatch.setenv("TRAINIQ_CEO_EMAIL", "ceo@trainiq.com")
    from importlib import reload
    import utils.platform_ceo as pc

    reload(pc)
    user = _User(
        email="impersonator@example.com",
        is_platform_staff=True,
        platform_staff_role="ceo",
    )
    assert pc.is_platform_ceo(user) is False


def test_only_ceo_email_is_platform_ceo(monkeypatch):
    monkeypatch.setenv("TRAINIQ_CEO_EMAIL", "ceo@trainiq.com")
    from importlib import reload
    import utils.platform_ceo as pc

    reload(pc)
    assert pc.is_platform_ceo(_User(email="ceo@trainiq.com")) is True
    assert pc.is_platform_ceo(_User(email="other@trainiq.com", platform_staff_role="ceo")) is False


def test_operations_view_ceo_only(monkeypatch):
    monkeypatch.setattr(
        "utils.platform_staff_permissions.is_platform_ceo",
        lambda u: u.employee_email == "ceo@trainiq.com",
    )
    ceo = _User(email="ceo@trainiq.com", is_platform_staff=True, platform_staff_role="ceo")
    admin = _User(email="admin@trainiq.com", is_platform_staff=True, platform_staff_role="admin")
    assert staff_has_permission(ceo, "operations.view")
    assert not staff_has_permission(admin, "operations.view")


def test_validate_staff_target_rejects_non_staff(monkeypatch):
    monkeypatch.setattr(
        "utils.platform_staff.user_on_platform_tenant",
        lambda u: True,
    )
    monkeypatch.setattr(
        "utils.platform_ceo.is_platform_ceo",
        lambda u: False,
    )

    class _FakeUser:
        id = 1
        is_platform_staff = False
        employee_email = "customer@corp.com"
        tenant_id = 5

    with patch("models.User") as UserMock:
        UserMock.query.get.return_value = _FakeUser()
        user, err = validate_staff_target(1)
    assert user is None
    assert "not platform staff" in (err or "").lower()


def test_validate_staff_target_rejects_wrong_tenant(monkeypatch):
    monkeypatch.setattr(
        "utils.platform_staff.user_on_platform_tenant",
        lambda u: False,
    )
    monkeypatch.setattr(
        "utils.platform_ceo.is_platform_ceo",
        lambda u: False,
    )

    class _FakeUser:
        id = 2
        is_platform_staff = True
        employee_email = "staff@corp.com"
        tenant_id = 5

    with patch("models.User") as UserMock:
        UserMock.query.get.return_value = _FakeUser()
        user, err = validate_staff_target(2)
    assert user is None
    assert "platform organization" in (err or "").lower()
