"""Optional safe auto-remediation after health scans."""
from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)


def auto_remediate_enabled() -> bool:
    return os.getenv('OPS_AUTO_REMEDIATE_SAFE', 'false').lower() in ('1', 'true', 'yes')


def maybe_auto_remediate_after_scan(monitor: dict) -> dict | None:
    """
    When enabled, apply safe index fixes automatically if issues detected.
    Never runs manual-tier recommendations.
    """
    if not auto_remediate_enabled():
        return None

    issue_count = int(monitor.get('issue_count') or 0)
    rec_count = int(monitor.get('recommendation_count') or 0)
    if issue_count <= 0 and rec_count <= 0:
        return None

    from utils.platform_ops_orchestrator import run_health_cycle

    logger.info(
        '[auto_remediate] issues=%s recommendations=%s — applying safe fixes',
        issue_count,
        rec_count,
    )
    return run_health_cycle(source='auto_remediate', apply_safe=True, blocking_lock=False)
