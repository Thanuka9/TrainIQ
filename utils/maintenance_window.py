"""Peak-traffic window guard for scheduled schema/DDL maintenance."""
from __future__ import annotations

import logging
import os
from datetime import datetime
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)


def _peak_timezone() -> ZoneInfo:
    name = (os.getenv('PLATFORM_PEAK_TZ') or 'UTC').strip()
    try:
        return ZoneInfo(name)
    except Exception:
        return ZoneInfo('UTC')


def _peak_hours() -> set[int]:
    raw = (os.getenv('PLATFORM_PEAK_HOURS') or '9-17').strip()
    hours: set[int] = set()
    for part in raw.split(','):
        part = part.strip()
        if not part:
            continue
        if '-' in part:
            a, b = part.split('-', 1)
            try:
                start, end = int(a), int(b)
                for h in range(min(start, end), max(start, end) + 1):
                    if 0 <= h <= 23:
                        hours.add(h)
            except ValueError:
                continue
        else:
            try:
                h = int(part)
                if 0 <= h <= 23:
                    hours.add(h)
            except ValueError:
                continue
    return hours or set(range(9, 18))


def is_peak_traffic_window(now: datetime | None = None) -> bool:
    if os.getenv('PLATFORM_PEAK_GUARD_ENABLED', 'true').lower() in ('0', 'false', 'no'):
        return False
    now = now or datetime.now(_peak_timezone())
    local = now.astimezone(_peak_timezone()) if now.tzinfo else now.replace(tzinfo=_peak_timezone())
    return local.hour in _peak_hours()


def scheduled_maintenance_allowed(*, manual: bool = False, source: str = '') -> tuple[bool, str]:
    """Block scheduler/cli auto maintenance during peak hours; CEO/manual bypass."""
    if manual or source in ('ceo_scan', 'ceo_apply', 'ceo_maintenance', 'ceo_agent', 'cli'):
        return True, 'manual'
    if is_peak_traffic_window():
        logger.info('[maintenance_window] Peak hour — deferring scheduled maintenance (%s)', source)
        return False, 'peak_hours'
    return True, 'ok'
