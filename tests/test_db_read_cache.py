"""Tests for short-lived ops read cache."""
from __future__ import annotations

import time
from unittest.mock import patch

import pytest

from utils.db_read_cache import get_cached, invalidate


@pytest.fixture(autouse=True)
def local_cache_only(monkeypatch):
    monkeypatch.setenv('OPS_CACHE_USE_REDIS', 'false')
    invalidate(None)


def test_get_cached_returns_fresh_when_ttl_zero():
    calls = {'n': 0}

    def producer():
        calls['n'] += 1
        return calls['n']

    assert get_cached('k1', 0, producer) == 1
    assert get_cached('k1', 0, producer) == 2


def test_get_cached_reuses_value_within_ttl():
    calls = {'n': 0}

    def producer():
        calls['n'] += 1
        return 'value'

    assert get_cached('k2', 60, producer) == 'value'
    assert get_cached('k2', 60, producer) == 'value'
    assert calls['n'] == 1


def test_get_cached_refreshes_after_ttl():
    calls = {'n': 0}

    def producer():
        calls['n'] += 1
        return calls['n']

    assert get_cached('k3', 0.05, producer) == 1
    time.sleep(0.06)
    assert get_cached('k3', 0.05, producer) == 2


def test_invalidate_single_key():
    calls = {'n': 0}

    def producer():
        calls['n'] += 1
        return calls['n']

    assert get_cached('k4', 60, producer) == 1
    invalidate('k4')
    assert get_cached('k4', 60, producer) == 2


def test_invalidate_all_clears_store():
    calls = {'n': 0}

    def producer():
        calls['n'] += 1
        return calls['n']

    get_cached('a', 60, producer)
    get_cached('b', 60, producer)
    assert calls['n'] == 2
    invalidate(None)
    get_cached('a', 60, producer)
    get_cached('b', 60, producer)
    assert calls['n'] == 4


def test_get_cached_uses_ops_cache_when_redis_enabled(monkeypatch):
    from utils import db_read_cache

    monkeypatch.setenv('OPS_CACHE_USE_REDIS', 'true')
    db_read_cache.invalidate()

    calls = {'n': 0}

    def producer():
        calls['n'] += 1
        return {'x': calls['n']}

    with patch('utils.ops_cache.get_json_cached', side_effect=lambda key, ttl, fn: fn()) as cache_mock:
        assert db_read_cache.get_cached('redis-key', 30, producer) == {'x': 1}
        cache_mock.assert_called_once()
