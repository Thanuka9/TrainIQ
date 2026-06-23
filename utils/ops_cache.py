"""Shared cache for JSON-safe ops payloads (Redis with in-process fallback)."""
from __future__ import annotations

import json
import logging
import os
import time
from collections.abc import Callable
from typing import Any, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar('T')

_redis_client = None
_local_lock = __import__('threading').Lock()
_local_store: dict[str, dict] = {}


def _redis_enabled() -> bool:
    return os.getenv('OPS_CACHE_USE_REDIS', 'true').lower() in ('1', 'true', 'yes')


def _get_redis():
    global _redis_client
    if _redis_client is not None:
        return _redis_client
    uri = (os.getenv('REDIS_URI') or '').strip()
    if not uri or uri.startswith('memory://'):
        return None
    try:
        import redis

        client = redis.from_url(uri, decode_responses=True, socket_connect_timeout=2)
        client.ping()
        _redis_client = client
        return _redis_client
    except Exception as exc:
        logger.debug('[ops_cache] Redis unavailable: %s', exc)
        return None


def get_json_cached(key: str, ttl_seconds: float, producer: Callable[[], T]) -> T:
    """Cache JSON-serializable payloads in Redis when available, else in-process."""
    if ttl_seconds <= 0:
        return producer()

    redis_key = f'trainiq:ops:{key}'
    r = _get_redis() if _redis_enabled() else None
    if r is not None:
        try:
            raw = r.get(redis_key)
            if raw:
                return json.loads(raw)
        except Exception as exc:
            logger.debug('[ops_cache] Redis read failed for %s: %s', key, exc)

    now = time.monotonic()
    with _local_lock:
        entry = _local_store.get(key)
        if entry and (now - entry['ts']) < ttl_seconds:
            return entry['value']

    value = producer()
    with _local_lock:
        _local_store[key] = {'ts': now, 'value': value}

    if r is not None:
        try:
            r.setex(redis_key, max(1, int(ttl_seconds)), json.dumps(value, default=str))
        except Exception as exc:
            logger.debug('[ops_cache] Redis write failed for %s: %s', key, exc)
    return value


def invalidate_json_cached(key: str | None = None) -> None:
    with _local_lock:
        if key is None:
            _local_store.clear()
        else:
            _local_store.pop(key, None)

    if not _redis_enabled():
        return
    r = _get_redis()
    if r is None:
        return
    try:
        if key is None:
            for rk in r.scan_iter('trainiq:ops:*', count=100):
                r.delete(rk)
        else:
            r.delete(f'trainiq:ops:{key}')
    except Exception as exc:
        logger.debug('[ops_cache] Redis invalidate failed: %s', exc)
