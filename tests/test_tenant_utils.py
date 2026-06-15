from utils.tenant_utils import (
    normalize_office_key,
    generate_office_key,
    email_domain,
    domain_matches_allowed,
    host_matches_allowed,
    is_trainiq_staff,
    is_platform_tenant,
    parse_domain_list,
    trainiq_staff_domains,
    trainiq_staff_emails,
)


def test_normalize_office_key():
    assert normalize_office_key("  abc123  ") == "ABC123"
    assert normalize_office_key("") is None
    assert normalize_office_key(None) is None


def test_generate_office_key_length():
    key = generate_office_key(12)
    assert len(key) == 12


def test_domain_matches_allowed_exact():
    assert domain_matches_allowed("user@acme.com", "acme.com, acme.co.uk")
    assert not domain_matches_allowed("user@evil-acme.com", "acme.com")


def test_host_matches_allowed():
    assert host_matches_allowed("portal.acme.com", "portal.acme.com, acme.com")
    assert not host_matches_allowed("evil.com", "acme.com")


def test_trainiq_staff_domains_default():
    assert "trainiq.com" in trainiq_staff_domains()


class _FakeUser:
    is_authenticated = True

    def __init__(self, email, *, is_platform_staff=False, tenant=None):
        self.employee_email = email
        self.is_platform_staff = is_platform_staff
        self.tenant = tenant


def test_is_trainiq_staff_requires_platform_staff_flag():
    assert not is_trainiq_staff(_FakeUser("ops@trainiq.com"))
    platform_tenant = type("T", (), {"office_key": "TRAINIQ"})()
    assert is_trainiq_staff(
        _FakeUser("ops@example.com", is_platform_staff=True, tenant=platform_tenant)
    )


def test_is_trainiq_staff_ceo_email():
    from utils.platform_ceo import PLATFORM_CEO_EMAIL

    assert is_trainiq_staff(_FakeUser(PLATFORM_CEO_EMAIL))


def test_trainiq_staff_emails_includes_ceo():
    from utils.platform_ceo import PLATFORM_CEO_EMAIL

    assert PLATFORM_CEO_EMAIL in trainiq_staff_emails()
