"""Retry helpers for transient PostgreSQL errors (deadlock, lock timeout)."""
from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import TypeVar

from sqlalchemy.exc import DBAPIError, OperationalError

logger = logging.getLogger(__name__)

T = TypeVar('T')

# 40001/40P01 deadlock, 55P03 lock_not_available
_RETRY_PG_CODES = frozenset({'40001', '40P01', '55P03'})


def is_retryable_db_error(exc: BaseException) -> bool:
    if 'deadlock detected' in str(exc).lower():
        return True
    orig = getattr(exc, 'orig', None)
    pgcode = getattr(orig, 'pgcode', None) or getattr(orig, 'sqlstate', None)
    if pgcode in _RETRY_PG_CODES:
        return True
    if isinstance(exc, (OperationalError, DBAPIError)):
        return is_retryable_db_error(exc.orig) if exc.orig else False
    return False


def run_with_db_retry(
    fn: Callable[[], T],
    *,
    attempts: int = 3,
    base_delay: float = 0.05,
    rollback: Callable[[], None] | None = None,
    label: str = 'db',
) -> T:
    """Run fn(); retry on deadlock / lock contention with exponential backoff."""
    last: BaseException | None = None
    for attempt in range(max(1, attempts)):
        try:
            return fn()
        except (OperationalError, DBAPIError) as exc:
            last = exc
            if not is_retryable_db_error(exc) or attempt >= attempts - 1:
                raise
            if rollback:
                try:
                    rollback()
                except Exception:
                    pass
            delay = base_delay * (2 ** attempt)
            logger.warning(
                '[db_retry] %s transient error (attempt %s/%s), retry in %.2fs: %s',
                label,
                attempt + 1,
                attempts,
                delay,
                exc,
            )
            time.sleep(delay)
    assert last is not None
    raise last
