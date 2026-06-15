"""Tests for platform staff role permissions."""
from types import SimpleNamespace

from utils.platform_staff_permissions import (
    ROLE_PERMISSIONS,
    staff_has_permission,
    effective_staff_role,
    get_role_catalog,
)


class _User:
    is_authenticated = True

    def __init__(self, *, email, is_platform_staff=False, platform_staff_role=None, is_super_admin=False):
        self.employee_email = email
        self.is_platform_staff = is_platform_staff
        self.platform_staff_role = platform_staff_role
        self.is_super_admin = is_super_admin


def test_support_cannot_view_revenue(monkeypatch):
    monkeypatch.setattr(
        "utils.platform_staff_permissions.is_platform_ceo",
        lambda u: False,
    )
    user = _User(email="s@example.com", is_platform_staff=True, platform_staff_role="support")
    assert staff_has_permission(user, "support.view")
    assert not staff_has_permission(user, "revenue.view")
    assert not staff_has_permission(user, "tenants.manage")


def test_admin_can_manage_tenants(monkeypatch):
    monkeypatch.setattr(
        "utils.platform_staff_permissions.is_platform_ceo",
        lambda u: False,
    )
    user = _User(email="a@example.com", is_platform_staff=True, platform_staff_role="admin")
    assert staff_has_permission(user, "tenants.manage")
    assert staff_has_permission(user, "revenue.view")


def test_ceo_has_all_permissions(monkeypatch):
    monkeypatch.setattr(
        "utils.platform_staff_permissions.is_platform_ceo",
        lambda u: u.employee_email == "ceo@trainiq.com",
    )
    user = _User(email="ceo@trainiq.com", is_platform_staff=True, platform_staff_role="ceo")
    assert staff_has_permission(user, "staff.manage")
    assert staff_has_permission(user, "revenue.view")


def test_role_catalog_lists_three_invite_roles():
    catalog = get_role_catalog()
    ids = [r["id"] for r in catalog]
    assert "support" in ids
    assert "ops" in ids
    assert "admin" in ids
    assert len(ROLE_PERMISSIONS["ops"]) > len(ROLE_PERMISSIONS["support"])
