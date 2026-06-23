"""Tests for database performance monitor and optimizer agent."""
from __future__ import annotations

import pytest
from sqlalchemy import text


def test_build_monitor_report_structure(app):
    with app.app_context():
        from utils.db_performance_monitor import build_monitor_report

        report = build_monitor_report()
        assert 'status' in report
        assert 'postgres' in report
        assert 'mongo' in report
        assert 'search_engine' in report
        assert report['search_engine']['elasticsearch_recommended'] is False


def test_sql_catalog_has_safe_indexes():
    from utils.db_catalog import PERFORMANCE_INDEX_DDL, SQL_OPTIMIZATION_CATALOG

    assert len(PERFORMANCE_INDEX_DDL) >= 10
    safe = [s for s in SQL_OPTIMIZATION_CATALOG if s.tier == 'safe']
    assert len(safe) == len(PERFORMANCE_INDEX_DDL)


def test_analyze_and_persist_creates_recommendations(app):
    with app.app_context():
        from extensions import db
        from models import DbOptimizationRecommendation, DbPerformanceSnapshot
        from utils.db_optimizer_agent import analyze_and_persist
        from utils.db_performance_monitor import build_monitor_report, save_snapshot

        try:
            db.session.execute(text('SELECT 1 FROM db_performance_snapshots LIMIT 1'))
        except Exception:
            pytest.skip('db_performance_snapshots table not migrated')

        report = build_monitor_report()
        snap = save_snapshot(report)
        db.session.commit()

        recs = analyze_and_persist(snap.id, report)
        assert isinstance(recs, list)
        assert snap.recommendation_count == len(recs)

        advisory = DbOptimizationRecommendation.query.filter_by(
            snapshot_id=snap.id,
            action_type='advisory',
        ).first()
        assert advisory is not None

        DbPerformanceSnapshot.query.filter_by(id=snap.id).delete()
        db.session.commit()


def test_apply_advisory_skips(app):
    with app.app_context():
        from extensions import db
        from models import DbOptimizationRecommendation, DbPerformanceSnapshot
        from utils.db_optimizer_agent import apply_recommendation

        try:
            db.session.execute(text('SELECT 1 FROM db_performance_snapshots LIMIT 1'))
        except Exception:
            pytest.skip('db_performance_snapshots table not migrated')

        snap = DbPerformanceSnapshot(status='healthy', issue_count=0, recommendation_count=1)
        db.session.add(snap)
        db.session.flush()
        rec = DbOptimizationRecommendation(
            snapshot_id=snap.id,
            action_type='advisory',
            target_key='test_advisory',
            tier='advisory',
            reason='Test advisory only.',
            status='pending',
        )
        db.session.add(rec)
        db.session.commit()

        ok, _msg = apply_recommendation(rec.id)
        assert ok is True
        db.session.refresh(rec)
        assert rec.status == 'skipped'

        db.session.delete(rec)
        db.session.delete(snap)
        db.session.commit()
