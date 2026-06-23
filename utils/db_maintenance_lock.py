"""Serialize platform maintenance so DDL does not deadlock with web traffic."""
from __future__ import annotations

import logging
import threading
from contextlib import contextmanager

from sqlalchemy import text

logger = logging.getLogger(__name__)

# Single global advisory lock for TrainIQ platform maintenance jobs.
PLATFORM_MAINTENANCE_LOCK_KEY = 847290001

_lock_depth = threading.local()


def _depth() -> int:
    return int(getattr(_lock_depth, 'value', 0) or 0)


def _set_depth(value: int) -> None:
    _lock_depth.value = value


@contextmanager
def platform_maintenance_lock(*, blocking: bool = False):
    """
    Prevent overlapping maintenance (CREATE INDEX, ALTER TABLE, Alembic, ANALYZE batches).

    Reentrant for nested calls in the same thread (full maintenance pipeline).

    blocking=False: skip work if another job holds the lock (background schedulers).
    blocking=True: wait until lock is free (CEO one-click maintenance).
    """
    if _depth() > 0:
        yield True
        return

    from extensions import db

    if db.engine.dialect.name != 'postgresql':
        yield True
        return

    conn = db.engine.connect()
    acquired = False
    try:
        if blocking:
            conn.execute(
                text('SELECT pg_advisory_lock(:key)'),
                {'key': PLATFORM_MAINTENANCE_LOCK_KEY},
            )
            acquired = True
        else:
            acquired = bool(
                conn.execute(
                    text('SELECT pg_try_advisory_lock(:key)'),
                    {'key': PLATFORM_MAINTENANCE_LOCK_KEY},
                ).scalar()
            )
        if not acquired:
            logger.info('[maintenance_lock] skipped — another maintenance job is active')
            yield False
            return
        _set_depth(_depth() + 1)
        try:
            yield True
        finally:
            _set_depth(max(0, _depth() - 1))
    finally:
        if acquired:
            try:
                conn.execute(
                    text('SELECT pg_advisory_unlock(:key)'),
                    {'key': PLATFORM_MAINTENANCE_LOCK_KEY},
                )
            except Exception as exc:
                logger.warning('[maintenance_lock] unlock failed: %s', exc)
        conn.close()
