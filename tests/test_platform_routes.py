from utils.tenant_utils import is_trainiq_staff


class _User:
    is_authenticated = True

    def __init__(self, email, *, is_platform_staff=False, tenant=None):
        self.employee_email = email
        self.is_platform_staff = is_platform_staff
        self.tenant = tenant


def test_is_trainiq_staff_requires_invite():
    assert not is_trainiq_staff(_User("ops@trainiq.com"))
    platform_tenant = type("T", (), {"office_key": "TRAINIQ"})()
    assert is_trainiq_staff(
        _User("ops@example.com", is_platform_staff=True, tenant=platform_tenant)
    )
    assert not is_trainiq_staff(_User("user@acme.com"))
