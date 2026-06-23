"""Short-lived cache for expensive read-only ops queries (Redis + in-process fallback)."""
from __future__ import annotations

import os
import threading
import time
from collections.abc import Callable
from typing import TypeVar

T = TypeVar('T')

_lock = threading.Lock()
_store: dict[str, dict] = {}


def _redis_enabled() -> bool:
    return os.getenv('OPS_CACHE_USE_REDIS', 'true').lower() in ('1', 'true', 'yes')


def get_cached(key: str, ttl_seconds: float, producer: Callable[[], T]) -> T:
    """Return cached value if fresh; otherwise call producer() and store."""
    if ttl_seconds <= 0:
        return producer()

    if _redis_enabled():
        try:
            from utils.ops_cache import get_json_cached

            return get_json_cached(f'db_read:{key}', ttl_seconds, producer)
        except Exception:
            pass

    now = time.monotonic()
    with _lock:
        entry = _store.get(key)
        if entry and (now - entry['ts']) < ttl_seconds:
            return entry['value']

    value = producer()
    with _lock:
        _store[key] = {'ts': now, 'value': value}
    return value


def invalidate(key: str | None = None) -> None:
    if key is not None and _redis_enabled():
        try:
            from utils.ops_cache import invalidate_json_cached

            invalidate_json_cached(f'db_read:{key}')
        except Exception:
            pass
    with _lock:
        if key is None:
            _store.clear()
        else:
            _store.pop(key, None)
