"""Tests for platform staff helpers."""
from utils.tenant_utils import is_trainiq_staff, trainiq_staff_domains


class _User:
    is_authenticated = True

    def __init__(self, email):
        self.employee_email = email


def test_trainiq_staff_domains_includes_default():
    assert "trainiq.com" in trainiq_staff_domains()


def test_is_trainiq_staff_email():
    assert is_trainiq_staff(_User("ops@trainiq.com"))
    assert not is_trainiq_staff(_User("user@acme.com"))
