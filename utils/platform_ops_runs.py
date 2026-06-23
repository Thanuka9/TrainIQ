"""Persist unified audit records for health scans and ops actions."""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)


def start_ops_run(
    *,
    source: str,
    trigger: str = 'scheduled',
    actor_user_id: int | None = None,
) -> int | None:
    from extensions import db
    from models import PlatformOpsRun

    try:
        run = PlatformOpsRun(
            source=source,
            trigger=trigger,
            actor_user_id=actor_user_id,
            status='running',
        )
        db.session.add(run)
        db.session.commit()
        return run.id
    except Exception as exc:
        db.session.rollback()
        logger.warning('[platform_ops_runs] could not start run: %s', exc)
        return None


def complete_ops_run(
    run_id: int | None,
    *,
    status: str,
    result: dict[str, Any],
    snapshot_id: int | None = None,
) -> None:
    if not run_id:
        return
    from extensions import db
    from models import PlatformOpsRun

    try:
        run = db.session.get(PlatformOpsRun, run_id)
        if not run:
            return
        monitor = result.get('monitor') or {}
        indexes = result.get('indexes') or {}
        run.completed_at = datetime.utcnow()
        run.status = status
        run.snapshot_id = snapshot_id or monitor.get('snapshot_id')
        run.issue_count = monitor.get('issue_count')
        run.indexes_applied = int(indexes.get('applied', 0) or 0)
        run.indexes_failed = int(indexes.get('failed', 0) or 0)
        run.result_json = json.dumps(result, default=str)[:8000]
        run.error_message = result.get('error')
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        logger.warning('[platform_ops_runs] complete failed run_id=%s: %s', run_id, exc)


def latest_ops_runs(limit: int = 20) -> list[dict[str, Any]]:
    from models import PlatformOpsRun

    try:
        rows = (
            PlatformOpsRun.query.order_by(PlatformOpsRun.started_at.desc())
            .limit(max(1, min(limit, 100)))
            .all()
        )
    except Exception as exc:
        logger.debug('[platform_ops_runs] list skipped: %s', exc)
        return []

    out = []
    for run in rows:
        out.append({
            'id': run.id,
            'source': run.source,
            'trigger': run.trigger,
            'status': run.status,
            'started_at': run.started_at.isoformat() if run.started_at else None,
            'completed_at': run.completed_at.isoformat() if run.completed_at else None,
            'snapshot_id': run.snapshot_id,
            'issue_count': run.issue_count,
            'indexes_applied': run.indexes_applied,
            'indexes_failed': run.indexes_failed,
            'error_message': run.error_message,
        })
    return out
