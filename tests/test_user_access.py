"""Tests for unified user access helpers."""
from types import SimpleNamespace

from utils.user_access import can_upload_study_materials, effective_is_super_admin


class _User:
    is_authenticated = True

    def __init__(self, *, is_super_admin=False, designation_id=None, permissions=None):
        self.is_super_admin = is_super_admin
        self.designation_id = designation_id
        self.roles = []
        self._permissions = permissions or set()

    def has_permission(self, key):
        return key in self._permissions


def test_effective_super_admin_flag():
    user = _User(is_super_admin=True)
    assert effective_is_super_admin(user) is True


def test_can_upload_super_admin():
    assert can_upload_study_materials(_User(is_super_admin=True)) is True


def test_can_upload_designation_12():
    assert can_upload_study_materials(_User(designation_id=12)) is True
    assert can_upload_study_materials(_User(designation_id=3)) is False


def test_can_upload_unauthenticated():
    anon = SimpleNamespace(is_authenticated=False)
    assert can_upload_study_materials(anon) is False
