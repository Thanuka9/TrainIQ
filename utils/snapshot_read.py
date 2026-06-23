"""Read persisted DB monitor snapshots (no live probes)."""
from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


def _parse_json(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


def load_latest_snapshot_row():
    from extensions import db
    from models import DbPerformanceSnapshot
    from utils.db_retry import run_with_db_retry

    def _load():
        return (
            DbPerformanceSnapshot.query.order_by(DbPerformanceSnapshot.collected_at.desc())
            .first()
        )

    try:
        return run_with_db_retry(_load, rollback=db.session.rollback, label='snapshot_read')
    except Exception as exc:
        logger.debug('[snapshot_read] unavailable: %s', exc)
        return None


def load_latest_snapshot_payload() -> dict[str, Any]:
    """Latest snapshot as parsed JSON blobs for agents and ops UI."""
    snap = load_latest_snapshot_row()
    if not snap:
        return {
            'snapshot': None,
            'snapshot_id': None,
            'collected_at': None,
            'status': None,
            'issue_count': 0,
            'recommendation_count': 0,
            'summary': {},
            'postgres_stats': {},
            'mongo_stats': {},
            'tables_ready': False,
        }

    pending_recs = 0
    if snap:
        try:
            pending_recs = snap.recommendations.filter_by(status='pending').count()
        except Exception:
            pending_recs = 0

    return {
        'snapshot': snap,
        'snapshot_id': snap.id,
        'collected_at': snap.collected_at.isoformat() if snap.collected_at else None,
        'status': snap.status,
        'issue_count': snap.issue_count,
        'recommendation_count': snap.recommendation_count,
        'pending_recommendations': pending_recs,
        'summary': _parse_json(snap.summary_json),
        'postgres_stats': _parse_json(snap.postgres_stats_json),
        'mongo_stats': _parse_json(snap.mongo_stats_json),
        'tables_ready': True,
    }


def snapshot_age_seconds() -> float | None:
    snap = load_latest_snapshot_row()
    if not snap or not snap.collected_at:
        return None
    from datetime import datetime

    return (datetime.utcnow() - snap.collected_at).total_seconds()
