"""Tests for DB deadlock retry and maintenance lock."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from sqlalchemy.exc import OperationalError

from utils.db_retry import is_retryable_db_error, run_with_db_retry


def test_is_retryable_deadlock_message():
    exc = OperationalError('stmt', {}, Exception('deadlock detected'))
    assert is_retryable_db_error(exc) is True


def test_is_retryable_pgcode():
    orig = MagicMock()
    orig.pgcode = '40P01'
    exc = OperationalError('stmt', {}, orig)
    assert is_retryable_db_error(exc) is True


def test_run_with_db_retry_recovers():
    calls = {'n': 0}

    def flaky():
        calls['n'] += 1
        if calls['n'] < 2:
            raise OperationalError('stmt', {}, Exception('deadlock detected'))
        return 'ok'

    assert run_with_db_retry(flaky, attempts=3, base_delay=0) == 'ok'
    assert calls['n'] == 2


def test_run_with_db_retry_non_retryable_raises():
    def fail():
        raise OperationalError('stmt', {}, Exception('syntax error'))

    with pytest.raises(OperationalError):
        run_with_db_retry(fail, attempts=3, base_delay=0)


def test_maintenance_lock_reentrant(app):
    with app.app_context():
        from utils.db_maintenance_lock import platform_maintenance_lock

        with platform_maintenance_lock(blocking=True):
            with platform_maintenance_lock(blocking=True):
                assert True
