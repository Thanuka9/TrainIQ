"""Analyze DB monitor reports and apply optimizations from db_catalog."""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from typing import Any

from sqlalchemy import inspect, text

from utils.db_catalog import (
    ADVISORY_MESSAGES,
    SQL_OPTIMIZATION_CATALOG,
)
from utils.mongo_catalog import (
    GRIDFS_RECOMMENDED_INDEXES,
    MONGO_COMPOUND_INDEX_CATALOG,
    MONGO_INDEX_CATALOG,
)

logger = logging.getLogger(__name__)


def _invalidate_ops_read_caches() -> None:
    try:
        from utils.platform_ops import invalidate_ops_read_caches
        invalidate_ops_read_caches()
    except Exception:
        pass


def _index_exists(conn, table: str, index_name: str) -> bool:
    insp = inspect(conn)
    if table not in insp.get_table_names():
        return True
    return any(idx['name'] == index_name for idx in insp.get_indexes(table))


def _extension_exists(conn, name: str) -> bool:
    row = conn.execute(
        text('SELECT 1 FROM pg_extension WHERE extname = :name'),
        {'name': name},
    ).fetchone()
    return row is not None


def _catalog_item_missing(conn, spec, existing_indexes: set[str]) -> bool:
    if spec.index_name and spec.index_name in existing_indexes:
        return False
    if spec.key == 'extension_pg_trgm' and _extension_exists(conn, 'pg_trgm'):
        return False
    if spec.key == 'course_notes_fts_column':
        insp = inspect(conn)
        if 'course_notes' not in insp.get_table_names():
            return False
        cols = {c['name'] for c in insp.get_columns('course_notes')}
        return 'content_search' not in cols
    if spec.key == 'course_notes_fts_backfill':
        return 'ix_course_notes_content_fts' not in existing_indexes
    if spec.index_name:
        return spec.index_name not in existing_indexes
    return True


def _apply_mongo_index(mongo_db, payload: dict[str, Any]) -> None:
    coll = mongo_db[payload['collection']]
    kwargs: dict[str, Any] = {}
    if payload.get('unique'):
        kwargs['unique'] = True
    if payload.get('name'):
        kwargs['name'] = payload['name']
    if payload.get('fields'):
        coll.create_index(payload['fields'], **kwargs)
    else:
        coll.create_index(payload['field'], **kwargs)


def analyze_and_persist(snapshot_id: int, report: dict[str, Any]) -> list:
    """Create recommendation rows for a snapshot. Returns ORM recommendation list."""
    from extensions import db
    from models import DbOptimizationRecommendation, DbPerformanceSnapshot

    snapshot = db.session.get(DbPerformanceSnapshot, snapshot_id)
    if not snapshot:
        return []

    postgres = report.get('postgres') or {}
    mongo = report.get('mongo') or {}
    existing_indexes = set(postgres.get('index_names') or [])
    recs: list[DbOptimizationRecommendation] = []

    conn = db.engine.connect()
    try:
        if postgres.get('available'):
            for spec in SQL_OPTIMIZATION_CATALOG:
                if not _catalog_item_missing(conn, spec, existing_indexes):
                    continue
                recs.append(
                    DbOptimizationRecommendation(
                        snapshot_id=snapshot_id,
                        action_type='run_sql',
                        target_key=spec.key,
                        tier=spec.tier,
                        reason=spec.reason,
                        ddl=spec.ddl,
                        status='pending',
                    )
                )

            for issue in postgres.get('issues') or []:
                if issue.get('category') != 'seq_scan':
                    continue
                table = issue.get('table')
                if not table:
                    continue
                key = f'advisory_seq_scan_{table}'
                recs.append(
                    DbOptimizationRecommendation(
                        snapshot_id=snapshot_id,
                        action_type='advisory',
                        target_key=key,
                        tier='manual',
                        reason=issue.get('message', f'Review indexes for table {table}.'),
                        ddl=None,
                        status='pending',
                    )
                )

        if mongo.get('available'):
            coll_by_name = {c['name']: c for c in mongo.get('collections') or []}
            for spec in MONGO_INDEX_CATALOG:
                coll = coll_by_name.get(spec.collection)
                if not coll:
                    continue
                if spec.field not in (coll.get('missing_indexes') or []):
                    continue
                key = f'mongo_{spec.collection}_{spec.field}'
                recs.append(
                    DbOptimizationRecommendation(
                        snapshot_id=snapshot_id,
                        action_type='ensure_mongo_index',
                        target_key=key,
                        tier=spec.tier,
                        reason=spec.reason,
                        ddl=json.dumps({
                            'collection': spec.collection,
                            'field': spec.field,
                            'unique': spec.unique,
                        }),
                        status='pending',
                    )
                )

            for spec in MONGO_COMPOUND_INDEX_CATALOG:
                label = '+'.join(f[0] for f in spec.fields)
                missing = False
                for coll in mongo.get('collections') or []:
                    if coll['name'] != spec.collection:
                        continue
                    if label in (coll.get('missing_indexes') or []):
                        missing = True
                    break
                if not missing:
                    continue
                key = f'mongo_{spec.collection}_{label}'
                recs.append(
                    DbOptimizationRecommendation(
                        snapshot_id=snapshot_id,
                        action_type='ensure_mongo_index',
                        target_key=key,
                        tier=spec.tier,
                        reason=spec.reason,
                        ddl=json.dumps({
                            'collection': spec.collection,
                            'fields': [list(f) for f in spec.fields],
                            'unique': spec.unique,
                            'name': spec.name,
                        }),
                        status='pending',
                    )
                )

            for spec in GRIDFS_RECOMMENDED_INDEXES:
                if spec.tier != 'safe':
                    continue
                for coll in mongo.get('collections') or []:
                    if coll['name'] != spec.collection:
                        continue
                    if spec.field not in (coll.get('missing_indexes') or []):
                        continue
                    key = f'mongo_{spec.collection}_{spec.field.replace(".", "_")}'
                    recs.append(
                        DbOptimizationRecommendation(
                            snapshot_id=snapshot_id,
                            action_type='ensure_mongo_index',
                            target_key=key,
                            tier=spec.tier,
                            reason=spec.reason,
                            ddl=json.dumps({
                                'collection': spec.collection,
                                'field': spec.field,
                                'unique': spec.unique,
                            }),
                            status='pending',
                        )
                    )

        for item in ADVISORY_MESSAGES:
            recs.append(
                DbOptimizationRecommendation(
                    snapshot_id=snapshot_id,
                    action_type='advisory',
                    target_key=item['target_key'],
                    tier=item['tier'],
                    reason=item['reason'],
                    ddl=None,
                    status='skipped' if item['tier'] == 'advisory' else 'pending',
                )
            )
    finally:
        conn.close()

    for rec in recs:
        db.session.add(rec)

    snapshot.recommendation_count = len(recs)
    db.session.commit()
    return recs


def apply_recommendation(rec_id: int, *, actor_user_id: int | None = None) -> tuple[bool, str]:
    """Apply a single pending recommendation. Returns (success, message)."""
    from extensions import db
    from models import DbOptimizationRecommendation

    rec = db.session.get(DbOptimizationRecommendation, rec_id)
    if not rec:
        return False, 'Recommendation not found.'
    if rec.status not in ('pending', 'failed'):
        return False, f'Already {rec.status}.'

    if rec.action_type == 'advisory':
        rec.status = 'skipped'
        db.session.commit()
        return True, 'Advisory recorded — no action required.'

    try:
        if rec.action_type in ('create_index', 'run_sql'):
            if not rec.ddl:
                raise ValueError('Missing DDL for SQL recommendation.')
            from utils.db_maintenance_lock import platform_maintenance_lock

            with platform_maintenance_lock(blocking=True):
                from utils.ddl_executor import execute_postgres_ddl

                execute_postgres_ddl(db.engine, rec.ddl)
            rec.status = 'applied'
            rec.applied_at = datetime.utcnow()
            rec.error_message = None
            db.session.commit()
            logger.info(
                '[db_optimizer] Applied SQL %s (rec=%s, actor=%s)',
                rec.target_key,
                rec.id,
                actor_user_id,
            )
            _invalidate_ops_read_caches()
            return True, f'{rec.target_key} applied successfully.'

        if rec.action_type == 'ensure_mongo_index':
            payload = json.loads(rec.ddl or '{}')
            from mongodb_operations import get_mongo_connection

            _, mongo_db, _ = get_mongo_connection()
            if mongo_db is None:
                raise RuntimeError('MongoDB unavailable.')
            _apply_mongo_index(mongo_db, payload)
            rec.status = 'applied'
            rec.applied_at = datetime.utcnow()
            rec.error_message = None
            db.session.commit()
            target = payload.get('field') or payload.get('name') or 'compound'
            logger.info(
                '[db_optimizer] Ensured Mongo index %s.%s (rec=%s)',
                payload.get('collection'),
                target,
                rec.id,
            )
            _invalidate_ops_read_caches()
            return True, f"MongoDB index on {payload.get('collection')}.{target} ensured."

        raise ValueError(f'Unsupported action_type: {rec.action_type}')
    except Exception as exc:
        db.session.rollback()
        rec.status = 'failed'
        rec.error_message = str(exc)[:500]
        db.session.commit()
        logger.error('[db_optimizer] Failed rec=%s: %s', rec.id, exc)
        return False, str(exc)


def _apply_recommendations_for_tiers(
    snapshot_id: int | None,
    tiers: tuple[str, ...],
) -> dict[str, int]:
    from models import DbOptimizationRecommendation, DbPerformanceSnapshot

    try:
        if snapshot_id is None:
            snap = (
                DbPerformanceSnapshot.query.order_by(DbPerformanceSnapshot.collected_at.desc())
                .first()
            )
            snapshot_id = snap.id if snap else None
        if not snapshot_id:
            return {'applied': 0, 'failed': 0, 'skipped': 0}

        pending = (
            DbOptimizationRecommendation.query.filter_by(
                snapshot_id=snapshot_id,
                status='pending',
            )
            .filter(DbOptimizationRecommendation.tier.in_(tiers))
            .filter(DbOptimizationRecommendation.action_type != 'advisory')
            .order_by(DbOptimizationRecommendation.id.asc())
            .all()
        )
    except Exception as exc:
        logger.warning('apply recommendations skipped: %s', exc)
        return {'applied': 0, 'failed': 0, 'skipped': 0}

    applied = failed = 0
    for rec in pending:
        ok, _ = apply_recommendation(rec.id)
        if ok:
            applied += 1
        else:
            failed += 1
    if applied or failed:
        _invalidate_ops_read_caches()
    return {'applied': applied, 'failed': failed, 'skipped': 0}


def apply_all_safe_recommendations(snapshot_id: int | None) -> dict[str, int]:
    from utils.db_maintenance_lock import platform_maintenance_lock

    with platform_maintenance_lock(blocking=True) as acquired:
        if not acquired:
            return {'applied': 0, 'failed': 0, 'skipped': 0, 'busy': 1}
        return _apply_recommendations_for_tiers(snapshot_id, ('safe',))


def apply_all_manual_recommendations(snapshot_id: int | None) -> dict[str, int]:
    from utils.db_maintenance_lock import platform_maintenance_lock

    with platform_maintenance_lock(blocking=True) as acquired:
        if not acquired:
            return {'applied': 0, 'failed': 0, 'skipped': 0, 'busy': 1}
        return _apply_recommendations_for_tiers(snapshot_id, ('manual',))


def apply_all_pending_recommendations(snapshot_id: int | None) -> dict[str, int]:
    from utils.db_maintenance_lock import platform_maintenance_lock

    with platform_maintenance_lock(blocking=True) as acquired:
        if not acquired:
            return {'applied': 0, 'failed': 0, 'skipped': 0, 'busy': 1}
        return _apply_recommendations_for_tiers(snapshot_id, ('safe', 'manual'))


def auto_apply_safe_recommendations(snapshot_id: int) -> dict[str, int]:
    if os.getenv('DB_OPTIMIZER_AUTO_APPLY', '').lower() not in ('1', 'true', 'yes'):
        return {'applied': 0, 'failed': 0, 'skipped': 0}
    return apply_all_safe_recommendations(snapshot_id)


def run_monitor_cycle(*, auto_apply_safe: bool = False, force_probe: bool = False) -> dict[str, Any]:
    from utils.db_performance_monitor import build_monitor_report, save_snapshot
    from utils.ops_probe_schedule import monitor_skip_result, should_collect_fresh_probe

    allowed, _reason = should_collect_fresh_probe(force=force_probe)
    if not allowed:
        return monitor_skip_result()

    report = build_monitor_report()
    snapshot = save_snapshot(report)
    from extensions import db
    db.session.commit()

    analyze_and_persist(snapshot.id, report)
    auto_result = {'applied': 0, 'failed': 0, 'skipped': 0}
    if auto_apply_safe:
        auto_result = auto_apply_safe_recommendations(snapshot.id)

    try:
        from utils.platform_ops import invalidate_ops_read_caches
        invalidate_ops_read_caches()
    except Exception:
        pass

    return {
        'snapshot_id': snapshot.id,
        'status': report['status'],
        'issue_count': report['issue_count'],
        'auto_apply': auto_result,
    }


def latest_snapshot_summary() -> dict[str, Any] | None:
    from extensions import db
    from models import DbPerformanceSnapshot
    from utils.db_retry import run_with_db_retry

    def _load():
        return (
            DbPerformanceSnapshot.query.order_by(DbPerformanceSnapshot.collected_at.desc())
            .first()
        )

    try:
        snap = run_with_db_retry(_load, rollback=db.session.rollback, label='latest_snapshot')
    except Exception as exc:
        logger.debug('latest_snapshot_summary skipped: %s', exc)
        return None
    if not snap:
        return None
    summary = {}
    if snap.summary_json:
        try:
            summary = json.loads(snap.summary_json)
        except json.JSONDecodeError:
            summary = {}
    pending = snap.recommendations.filter_by(status='pending').count()
    return {
        'snapshot_id': snap.id,
        'collected_at': snap.collected_at.isoformat() if snap.collected_at else None,
        'status': snap.status,
        'issue_count': snap.issue_count,
        'recommendation_count': snap.recommendation_count,
        'pending_recommendations': pending,
        'summary': summary,
    }
