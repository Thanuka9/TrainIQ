"""Tests for safe tenant/user ORM loads."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from sqlalchemy.exc import OperationalError

from utils.tenant_db import load_tenant_by_id, load_user_by_id


def test_load_tenant_by_id_none():
    assert load_tenant_by_id(None) is None


def test_load_tenant_by_id_retries(app):
    with app.app_context():
        from extensions import db

        calls = {'n': 0}

        def fake_get(model, pk):
            calls['n'] += 1
            if calls['n'] < 2:
                raise OperationalError('stmt', {}, Exception('deadlock detected'))
            return MagicMock(id=pk, name='Acme')

        with patch.object(db.session, 'get', side_effect=fake_get):
            tenant = load_tenant_by_id(33, label='test')
        assert tenant is not None
        assert calls['n'] == 2


def test_load_user_by_id_returns_none_on_failure(app):
    with app.app_context():
        from extensions import db

        with patch.object(db.session, 'get', side_effect=OperationalError('stmt', {}, Exception('syntax error'))):
            assert load_user_by_id(1) is None
