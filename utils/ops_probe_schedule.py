"""Coordinate DB/Mongo live probes to avoid duplicate scheduled work."""
from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)


def probe_min_interval_minutes() -> int:
    return max(5, int(os.getenv('OPS_PROBE_MIN_INTERVAL_MINUTES', '15')))


def agents_after_monitor_minutes() -> int:
    return max(0, int(os.getenv('OPS_AGENTS_DELAY_AFTER_MONITOR_MINUTES', '5')))


def should_collect_fresh_probe(*, force: bool = False) -> tuple[bool, str]:
    """Return (allowed, reason) before running live pg/mongo collectors."""
    if force:
        return True, 'forced'

    from utils.snapshot_read import snapshot_age_seconds

    age = snapshot_age_seconds()
    if age is None:
        return True, 'no_snapshot'

    min_secs = probe_min_interval_minutes() * 60
    if age < min_secs:
        logger.info(
            '[ops_probe] Skipping live probe — snapshot age %.0fs < %ss cooldown',
            age,
            min_secs,
        )
        return False, 'probe_cooldown'

    return True, 'ok'


def skip_ops_agents_refresh() -> tuple[bool, str]:
    """Defer agent refresh if monitor just ran (snapshot still fresh for agents)."""
    from utils.snapshot_read import snapshot_age_seconds

    age = snapshot_age_seconds()
    if age is None:
        return False, 'no_snapshot'

    delay = agents_after_monitor_minutes() * 60
    if age < delay:
        return True, 'awaiting_post_monitor_delay'
    return False, 'ok'


def monitor_skip_result() -> dict[str, Any]:
    from utils.db_optimizer_agent import latest_snapshot_summary

    latest = latest_snapshot_summary() or {}
    return {
        'skipped': True,
        'reason': 'probe_cooldown',
        'status': latest.get('status', 'unknown'),
        'snapshot_id': latest.get('snapshot_id'),
        'issue_count': latest.get('issue_count', 0),
    }
