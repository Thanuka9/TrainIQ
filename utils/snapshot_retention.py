"""Prune old DB performance snapshots and metric samples."""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


def snapshot_retention_days() -> int:
    return max(14, int(os.getenv('DB_SNAPSHOT_RETENTION_DAYS', '90')))


def snapshot_max_count() -> int:
    return max(50, int(os.getenv('DB_SNAPSHOT_MAX_COUNT', '500')))


def run_snapshot_retention() -> dict:
    from extensions import db
    from models import DbPerformanceSnapshot
    from utils.db_metric_samples import purge_old_metric_samples

    cutoff = datetime.utcnow() - timedelta(days=snapshot_retention_days())
    snapshots_deleted = 0
    try:
        snapshots_deleted = (
            DbPerformanceSnapshot.query.filter(DbPerformanceSnapshot.collected_at < cutoff)
            .delete(synchronize_session=False)
        )
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        logger.warning('[snapshot_retention] age purge failed: %s', exc)

    count_deleted = 0
    try:
        total = DbPerformanceSnapshot.query.count()
        excess = total - snapshot_max_count()
        if excess > 0:
            old_ids = [
                row.id
                for row in (
                    DbPerformanceSnapshot.query.order_by(DbPerformanceSnapshot.collected_at.asc())
                    .limit(excess)
                    .all()
                )
            ]
            if old_ids:
                count_deleted = (
                    DbPerformanceSnapshot.query.filter(DbPerformanceSnapshot.id.in_(old_ids))
                    .delete(synchronize_session=False)
                )
                db.session.commit()
    except Exception as exc:
        db.session.rollback()
        logger.warning('[snapshot_retention] count cap purge failed: %s', exc)

    samples_deleted = purge_old_metric_samples()
    result = {
        'snapshots_deleted': int(snapshots_deleted or 0) + int(count_deleted or 0),
        'samples_deleted': samples_deleted,
        'retention_days': snapshot_retention_days(),
        'max_count': snapshot_max_count(),
    }
    logger.info('[snapshot_retention] %s', result)
    return result
