"""Phase 1 security: support read-only, domain cache."""
from types import SimpleNamespace
from unittest.mock import patch

import pytest


class _Session(dict):
    def get(self, key, default=None):
        return super().get(key, default)

    def pop(self, key, default=None):
        return super().pop(key, default)


def test_support_readonly_by_default(monkeypatch):
    import utils.support_access as sa

    sess = _Session({'platform_support': True})
    monkeypatch.setattr(sa, 'session', sess)
    monkeypatch.setattr('utils.tenant_utils.is_trainiq_staff', lambda u=None: True)

    assert sa.is_support_readonly() is True
    assert sa.can_support_write() is False


def test_support_write_after_elevation(monkeypatch):
    import utils.support_access as sa

    sess = _Session({'platform_support': True})
    monkeypatch.setattr(sa, 'session', sess)
    monkeypatch.setattr('utils.tenant_utils.is_trainiq_staff', lambda u=None: True)
    monkeypatch.setattr('utils.platform_staff_permissions.staff_has_permission', lambda u, p: False)

    sa.elevate_support_write_access()
    assert sa.is_support_readonly() is False
    assert sa.can_support_write() is True


def test_tenants_manage_still_readonly_without_elevation(monkeypatch):
    import utils.support_access as sa

    sess = _Session({'platform_support': True})
    monkeypatch.setattr(sa, 'session', sess)
    monkeypatch.setattr('utils.tenant_utils.is_trainiq_staff', lambda u=None: True)
    monkeypatch.setattr('utils.platform_staff_permissions.staff_has_permission', lambda u, p: p == 'tenants.manage')

    assert sa.is_support_readonly() is True
    assert sa.can_support_write() is False


def test_effective_super_admin_false_in_readonly_support(monkeypatch):
    import utils.support_access as sa

    sess = _Session({'platform_support': True})
    monkeypatch.setattr(sa, 'session', sess)
    monkeypatch.setattr('utils.tenant_utils.is_trainiq_staff', lambda u=None: True)

    user = SimpleNamespace(is_authenticated=True, is_super_admin=True)
    assert sa.can_support_write(user) is False


def test_tenant_domain_cache_uses_ops_cache(monkeypatch):
    from utils import tenant_domain_cache as tdc

    monkeypatch.setenv('OPS_CACHE_USE_REDIS', 'false')
    rows = [{'id': 7, 'allowed_domain': 'acme.test'}]

    with patch('utils.tenant_domain_cache._load_domain_rows', return_value=rows):
        with patch('utils.tenant_db.load_tenant_by_id') as load_mock:
            load_mock.return_value = SimpleNamespace(id=7, allowed_domain='acme.test')
            tenants = tdc.load_tenants_with_allowed_domains_cached()
    assert len(tenants) == 1
    assert tenants[0].id == 7


def test_resolve_tenant_id_for_host(monkeypatch):
    from utils.tenant_domain_cache import resolve_tenant_id_for_host

    with patch(
        'utils.tenant_domain_cache._load_domain_rows',
        return_value=[{'id': 3, 'allowed_domain': 'corp.example.com'}],
    ):
        assert resolve_tenant_id_for_host('app.corp.example.com') is None
        assert resolve_tenant_id_for_host('corp.example.com') == 3
