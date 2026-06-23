"""Persist time-series metric samples from monitor snapshots."""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta
from typing import Any

logger = logging.getLogger(__name__)

METRIC_KEYS = (
    'pg.cache_hit_ratio',
    'pg.database_size_mb',
    'pg.connections_active',
    'pg.connections_max',
    'pg.issue_count',
    'mongo.storage_mb',
    'mongo.tenant_db_count',
)


def _extract_metrics(report: dict[str, Any]) -> list[tuple[str, float]]:
    out: list[tuple[str, float]] = []
    pg = report.get('postgres') or {}
    cap = pg.get('capacity') or {}
    conns = cap.get('connections') or {}
    mongo = report.get('mongo') or {}
    server = mongo.get('server') or {}

    mapping = {
        'pg.cache_hit_ratio': cap.get('cache_hit_ratio'),
        'pg.database_size_mb': cap.get('database_size_mb'),
        'pg.connections_active': conns.get('active'),
        'pg.connections_max': conns.get('max'),
        'pg.issue_count': report.get('issue_count'),
        'mongo.storage_mb': server.get('total_storage_mb'),
        'mongo.tenant_db_count': mongo.get('tenant_db_count'),
    }
    for key, val in mapping.items():
        if val is None:
            continue
        try:
            out.append((key, float(val)))
        except (TypeError, ValueError):
            continue
    return out


def record_metric_samples(snapshot_id: int, report: dict[str, Any]) -> int:
    from extensions import db
    from models import DbMetricSample

    collected_at = datetime.utcnow()
    rows = 0
    for key, value in _extract_metrics(report):
        db.session.add(
            DbMetricSample(
                collected_at=collected_at,
                snapshot_id=snapshot_id,
                metric_key=key,
                value=value,
            )
        )
        rows += 1
    if rows:
        try:
            db.session.flush()
        except Exception as exc:
            logger.warning('[metric_samples] flush failed: %s', exc)
            db.session.rollback()
            return 0
    return rows


def recent_metric_series(metric_key: str, *, limit: int = 48) -> list[dict[str, Any]]:
    from models import DbMetricSample

    try:
        rows = (
            DbMetricSample.query.filter_by(metric_key=metric_key)
            .order_by(DbMetricSample.collected_at.desc())
            .limit(max(1, min(limit, 500)))
            .all()
        )
    except Exception:
        return []
    out = []
    for row in reversed(rows):
        out.append({
            't': row.collected_at.isoformat() if row.collected_at else None,
            'v': row.value,
            'snapshot_id': row.snapshot_id,
        })
    return out


def ops_trend_bundle(*, limit: int = 24) -> dict[str, list[dict[str, Any]]]:
    return {
        'pg.cache_hit_ratio': recent_metric_series('pg.cache_hit_ratio', limit=limit),
        'pg.database_size_mb': recent_metric_series('pg.database_size_mb', limit=limit),
        'pg.connections_active': recent_metric_series('pg.connections_active', limit=limit),
        'pg.issue_count': recent_metric_series('pg.issue_count', limit=limit),
    }


def purge_old_metric_samples() -> int:
    days = max(30, int(os.getenv('DB_METRIC_SAMPLE_RETENTION_DAYS', '365')))
    cutoff = datetime.utcnow() - timedelta(days=days)
    from extensions import db
    from models import DbMetricSample

    try:
        deleted = (
            DbMetricSample.query.filter(DbMetricSample.collected_at < cutoff)
            .delete(synchronize_session=False)
        )
        db.session.commit()
        return int(deleted or 0)
    except Exception as exc:
        db.session.rollback()
        logger.warning('[metric_samples] purge failed: %s', exc)
        return 0
