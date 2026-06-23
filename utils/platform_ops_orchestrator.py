"""Single orchestration entry for platform health scans and safe applies."""
from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)

# Explicit human/CEO actions — apply safe indexes even when DB_OPTIMIZER_AUTO_APPLY=false.
EXPLICIT_APPLY_SOURCES = frozenset({'cli', 'ceo_apply', 'ceo_maintenance'})

_SCHEDULED_SOURCES = frozenset({'scheduler', 'ops_worker'})


def _should_apply_safe(*, source: str, apply_safe: bool) -> bool:
    if not apply_safe:
        return False
    if source in EXPLICIT_APPLY_SOURCES:
        return True
    return os.getenv('DB_OPTIMIZER_AUTO_APPLY', '').lower() in ('1', 'true', 'yes')


def _trigger_for_source(source: str) -> str:
    if source in _SCHEDULED_SOURCES:
        return 'scheduled'
    if source in EXPLICIT_APPLY_SOURCES or source in ('ceo_scan', 'ceo_agent'):
        return 'manual'
    return 'manual' if source == 'cli' else 'scheduled'


_EXPLICIT_PROBE_SOURCES = frozenset({'cli', 'ceo_scan', 'ceo_agent', 'ceo_apply', 'ceo_maintenance'})


def run_health_cycle(
    *,
    source: str = 'scheduler',
    apply_safe: bool = False,
    blocking_lock: bool = False,
    actor_user_id: int | None = None,
) -> dict[str, Any]:
    """
    Collect DB metrics, analyze, optionally apply safe-tier indexes.

    All schedulers, CLI tools, and agent scan actions should call this instead of
    duplicating monitor + apply logic.
    """
    from utils.db_maintenance_lock import platform_maintenance_lock
    from utils.db_optimizer_agent import apply_all_safe_recommendations, run_monitor_cycle
    from utils.ops_alerts import maybe_send_ops_alert
    from utils.platform_ops import invalidate_ops_read_caches
    from utils.platform_ops_runs import complete_ops_run, start_ops_run

    started = datetime.utcnow()
    run_id = start_ops_run(
        source=source,
        trigger=_trigger_for_source(source),
        actor_user_id=actor_user_id,
    )

    with platform_maintenance_lock(blocking=blocking_lock) as acquired:
        if not acquired:
            result = {
                'skipped': True,
                'reason': 'maintenance_lock_busy',
                'source': source,
                'status': 'skipped',
            }
            complete_ops_run(run_id, status='skipped', result=result)
            return result

        try:
            force_probe = source in _EXPLICIT_PROBE_SOURCES
            monitor = run_monitor_cycle(auto_apply_safe=False, force_probe=force_probe)
            indexes = {'applied': 0, 'failed': 0, 'skipped': 0, 'busy': 0}

            do_apply = _should_apply_safe(source=source, apply_safe=apply_safe)
            if do_apply and source in _SCHEDULED_SOURCES:
                from utils.maintenance_window import scheduled_maintenance_allowed

                allowed, peak_reason = scheduled_maintenance_allowed(manual=False, source=source)
                if not allowed:
                    do_apply = False
                    logger.info('[platform_ops] Deferred safe apply during %s', peak_reason)

            if do_apply:
                indexes = apply_all_safe_recommendations(monitor.get('snapshot_id'))
            elif source in _SCHEDULED_SOURCES:
                from utils.ops_auto_remediate import maybe_auto_remediate_after_scan

                auto_result = maybe_auto_remediate_after_scan(monitor)
                if auto_result:
                    indexes = auto_result.get('indexes') or indexes
                    monitor = auto_result.get('monitor') or monitor

            status = monitor.get('status', 'unknown')
            if monitor.get('skipped'):
                status = 'skipped'
            if indexes.get('failed', 0) > 0 and status == 'healthy':
                status = 'warning'

            result = {
                'source': source,
                'status': status,
                'monitor': monitor,
                'indexes': indexes,
                'started_at': started.isoformat(),
                'completed_at': datetime.utcnow().isoformat(),
            }
            logger.info(
                '[platform_ops] health cycle (%s) — status=%s issues=%s applied=%s',
                source,
                status,
                monitor.get('issue_count', 0),
                indexes.get('applied', 0),
            )
            complete_ops_run(
                run_id,
                status=status,
                result=result,
                snapshot_id=monitor.get('snapshot_id'),
            )
            maybe_send_ops_alert(status=status, source=source, detail=result)
            return result
        except Exception as exc:
            logger.error('[platform_ops] health cycle failed (%s): %s', source, exc, exc_info=True)
            result = {'source': source, 'error': str(exc), 'status': 'failed'}
            complete_ops_run(run_id, status='failed', result=result)
            maybe_send_ops_alert(status='critical', source=source, detail=result)
            return result
        finally:
            try:
                invalidate_ops_read_caches()
            except Exception:
                pass


def queue_or_run_health_cycle(
    *,
    source: str = 'scheduler',
    apply_safe: bool = False,
    blocking_lock: bool = False,
    actor_user_id: int | None = None,
) -> dict[str, Any]:
    """Run synchronously or queue on the ops event bus when split across workers."""
    from utils.event_bus import event_bus_enabled, publish_health_cycle
    from utils.service_mode import is_ops_worker_process

    if event_bus_enabled() and not is_ops_worker_process():
        msg_id = publish_health_cycle(
            source=source,
            apply_safe=apply_safe,
            actor_user_id=actor_user_id,
        )
        if msg_id:
            return {
                'queued': True,
                'status': 'queued',
                'source': source,
                'message_id': msg_id,
            }

    return run_health_cycle(
        source=source,
        apply_safe=apply_safe,
        blocking_lock=blocking_lock,
        actor_user_id=actor_user_id,
    )
