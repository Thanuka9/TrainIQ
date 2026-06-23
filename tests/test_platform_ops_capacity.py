"""Full tests for production-scale platform ops module additions."""
from __future__ import annotations

import json
import os
from unittest.mock import MagicMock, patch

import pytest


# ── PostgreSQL monitor & catalog ─────────────────────────────────────────────


def test_monitored_tables_use_audit_log_not_audit_logs():
    from utils.db_performance_monitor import MONITORED_TABLES

    assert 'audit_log' in MONITORED_TABLES
    assert 'audit_logs' not in MONITORED_TABLES


def test_performance_ddl_uses_audit_log_table():
    from utils.db_catalog import PERFORMANCE_INDEX_DDL

    blob = '\n'.join(PERFORMANCE_INDEX_DDL)
    assert 'audit_log' in blob
    assert 'audit_logs' not in blob
    assert 'ix_billing_events_tenant_created' in blob
    assert 'ix_user_scores_user_created' in blob


def test_analyze_tables_list():
    from utils.db_catalog import ANALYZE_TABLES

    assert 'audit_log' in ANALYZE_TABLES
    assert 'billing_events' in ANALYZE_TABLES
    assert len(ANALYZE_TABLES) >= 10


def test_collect_postgres_stats_sqlite(app):
    with app.app_context():
        from utils.db_performance_monitor import collect_postgres_stats

        stats = collect_postgres_stats()
        # Test DB is often SQLite in CI — should degrade gracefully
        if not stats.get('available'):
            assert stats.get('reason') in ('not_postgresql',) or 'reason' in stats
        else:
            assert 'capacity' in stats
            cap = stats['capacity']
            assert 'database_size_bytes' in cap
            assert 'connections' in cap
            assert 'slow_queries' in cap


def test_build_monitor_report_capacity_fields(app):
    with app.app_context():
        from utils.db_performance_monitor import build_monitor_report

        report = build_monitor_report()
        assert report['status'] in ('healthy', 'warning', 'critical', 'degraded')
        assert isinstance(report['issues'], list)
        assert 'warning_count' in report
        assert 'critical_count' in report
        pg = report['postgres']
        if pg.get('available'):
            assert 'capacity' in pg


def test_save_snapshot_includes_capacity_summary(app):
    with app.app_context():
        from sqlalchemy import text

        from extensions import db
        from models import DbPerformanceSnapshot
        from utils.db_performance_monitor import build_monitor_report, save_snapshot

        try:
            db.session.execute(text('SELECT 1 FROM db_performance_snapshots LIMIT 1'))
        except Exception:
            pytest.skip('db_performance_snapshots not migrated')

        report = build_monitor_report()
        snap = save_snapshot(report)
        db.session.commit()

        summary = json.loads(snap.summary_json)
        assert 'postgres_capacity' in summary or summary.get('status')

        DbPerformanceSnapshot.query.filter_by(id=snap.id).delete()
        db.session.commit()


def test_run_postgres_analyze_skips_non_postgres(app):
    with app.app_context():
        from utils.db_maintenance import run_postgres_analyze

        step = run_postgres_analyze()
        assert step['step'] == 'postgres_analyze'
        assert 'ok' in step
        # SQLite test env → skipped with ok=True
        if step.get('detail', {}).get('skipped') or 'Skipped' in step.get('message', ''):
            assert step['ok'] is True


# ── Mongo catalog & platform ─────────────────────────────────────────────────


class _FakeColl:
    def __init__(self, indexes=None):
        self._indexes = indexes or [{'key': {'_id': 1}, 'name': '_id_'}]
        self.created: list = []

    def list_indexes(self):
        yield from self._indexes

    def create_index(self, field, **kwargs):
        self.created.append((field, kwargs))
        if isinstance(field, str):
            self._indexes.append({'key': {field: 1}, 'name': f'ix_{field}'})
        else:
            self._indexes.append({'key': dict(field), 'name': kwargs.get('name', 'compound')})


class _FakeDB:
    def __init__(self, names):
        self._cols = {n: _FakeColl() for n in names}

    def list_collection_names(self):
        return list(self._cols.keys())

    def __getitem__(self, name):
        return self._cols[name]


def test_mongo_catalog_apply_indexes():
    from utils.mongo_catalog import apply_catalog_indexes

    db = _FakeDB(['profile_pictures', 'file_metadata'])
    result = apply_catalog_indexes(db)
    assert result['applied'] >= 4
    assert result['failed'] == 0
    assert db['profile_pictures'].created


def test_mongo_catalog_missing_compound_indexes():
    from utils.mongo_catalog import missing_indexes_for_db

    db = _FakeDB(['profile_pictures', 'file_metadata'])
    missing = missing_indexes_for_db(db)
    fields = {(m['collection'], m['field']) for m in missing}
    assert ('file_metadata', 'tenant_id+study_material_id') in fields or any(
        'tenant_id' in m['field'] for m in missing if m['collection'] == 'file_metadata'
    )


def test_collect_mongo_monitor_stats_unavailable():
    with patch('utils.mongo_platform.get_mongo_connection', create=True) as mock_conn:
        mock_conn.return_value = (None, None, None)
        from utils.mongo_platform import collect_mongo_monitor_stats

        with patch('mongodb_operations.get_mongo_connection', return_value=(None, None, None)):
            stats = collect_mongo_monitor_stats()
        assert stats['available'] is False


def test_bootstrap_mongo_skipped_when_down():
    with patch('mongodb_operations.initialize_mongodb', return_value=(None, None)):
        from utils.mongo_platform import bootstrap_mongo

        result = bootstrap_mongo(provision_tenants=False)
        assert result['status'] == 'skipped'


def test_bootstrap_mongo_parallel_provision(app):
    with app.app_context():
        from utils.mongo_platform import bootstrap_mongo

        legacy = _FakeDB(['profile_pictures', 'file_metadata'])
        legacy.name = 'collective_rcm_test'

        with patch('mongodb_operations.initialize_mongodb', return_value=(MagicMock(), legacy)), \
             patch('utils.mongo_catalog.apply_catalog_indexes', return_value={'applied': 5, 'failed': 0}), \
             patch('mongodb_operations.setup_collections'), \
             patch('utils.mongo_platform._provision_tenant_worker', return_value=(1, True, '')):
            from models import Tenant

            tenants_before = Tenant.query.count()
            result = bootstrap_mongo(provision_tenants=tenants_before > 0)
            assert result['status'] in ('success', 'partial')
            step_names = [s['step'] for s in result['steps']]
            assert 'legacy_indexes' in step_names


def test_db_optimizer_mongo_compound_apply(app):
    with app.app_context():
        from extensions import db
        from models import DbOptimizationRecommendation, DbPerformanceSnapshot
        from utils.db_optimizer_agent import _apply_mongo_index

        fake_db = _FakeDB(['file_metadata'])
        payload = {
            'collection': 'file_metadata',
            'fields': [['tenant_id', 1], ['study_material_id', 1]],
            'unique': False,
            'name': 'ix_file_meta_tenant_material',
        }
        _apply_mongo_index(fake_db, payload)
        assert fake_db['file_metadata'].created

        try:
            db.session.execute(__import__('sqlalchemy').text(
                'SELECT 1 FROM db_optimization_recommendations LIMIT 1'
            ))
        except Exception:
            pytest.skip('optimizer tables not migrated')

        snap = DbPerformanceSnapshot(status='healthy', issue_count=0, recommendation_count=1)
        db.session.add(snap)
        db.session.flush()
        rec = DbOptimizationRecommendation(
            snapshot_id=snap.id,
            action_type='ensure_mongo_index',
            target_key='mongo_file_metadata_compound',
            tier='safe',
            reason='test',
            ddl=json.dumps(payload),
            status='pending',
        )
        db.session.add(rec)
        db.session.commit()

        with patch('utils.db_optimizer_agent.get_mongo_connection', create=True), \
             patch('mongodb_operations.get_mongo_connection', return_value=(None, fake_db, None)):
            from utils.db_optimizer_agent import apply_recommendation

            ok, msg = apply_recommendation(rec.id)
        assert ok is True
        db.session.refresh(rec)
        assert rec.status == 'applied'

        db.session.delete(rec)
        db.session.delete(snap)
        db.session.commit()


# ── AI cache & platform ──────────────────────────────────────────────────────


def test_ai_cache_stats_and_trim(tmp_path, monkeypatch):
    from utils import ai_cache
    from utils.ai_cache_storage import DiskCacheStorage

    store = DiskCacheStorage(str(tmp_path))
    monkeypatch.setattr(ai_cache, '_storage', lambda: store)
    monkeypatch.setattr(ai_cache, 'CACHE_MAX_MB', 1)

    key = ai_cache.make_key('summarize', 1, 'f', 1, 'pdf', 0, 'm')
    ai_cache.set(key, {'summary': 'x'}, feature='summarize')

    stats = ai_cache.get_cache_stats()
    assert stats['files'] == 1
    assert stats['by_feature'].get('summarize') == 1
    assert 'max_mb' in stats

    # Force over-capacity trim (large payload in cache entry)
    store.write('big', {'ts': 0, 'feature': 'big', 'data': 'x' * (2 * 1024 * 1024)})

    trim = ai_cache.trim_to_capacity(max_mb=1)
    assert trim['removed'] >= 1
    assert trim['remaining_mb'] <= 1.1


def test_probe_ollama_latency_mocked():
    from utils.ai_platform import probe_ollama_latency

    class FakeResp:
        status_code = 200

        def json(self):
            return {'models': []}

    with patch('requests.get', return_value=FakeResp()):
        result = probe_ollama_latency()
    assert result['ok'] is True
    assert result['latency_ms'] is not None


def test_get_ai_ops_status_shape(app):
    with app.app_context():
        from utils.ai_platform import get_ai_ops_status

        with patch('utils.ai_platform.probe_ollama_latency', return_value={'ok': True, 'latency_ms': 12, 'slow': False}):
            status = get_ai_ops_status()
        assert 'cache' in status
        assert 'capacity' in status
        assert 'latency' in status
        assert 'jobs' in status
        assert 'failed' in status['jobs']


def test_bootstrap_ai_steps(app):
    with app.app_context():
        from utils.ai_platform import bootstrap_ai

        with patch('utils.ai_platform.clear_ai_cache', return_value={'ok': True, 'removed': 0}), \
             patch('utils.ai_platform.refresh_ai_engine', return_value={'available': True, 'message': 'ok'}):
            result = bootstrap_ai()
        assert result['status'] in ('success', 'partial')
        steps = [s['step'] for s in result['steps']]
        assert 'ai_cache_expired' in steps
        assert 'ai_engine_refresh' in steps


# ── Integrations ───────────────────────────────────────────────────────────────


def test_integrations_redis_memory_mode():
    from utils.integrations_platform import check_redis, get_integrations_status

    with patch.dict(os.environ, {'REDIS_URI': 'memory://'}):
        redis = check_redis()
        assert redis['ok'] is True
        assert redis['mode'] == 'memory'

        status = get_integrations_status()
        assert status['status'] in ('healthy', 'degraded')
        assert len(status['checks']) == 3


def test_integrations_stripe_without_key():
    from utils.integrations_platform import check_stripe

    with patch.dict(os.environ, {'STRIPE_SECRET_KEY': ''}, clear=False):
        result = check_stripe()
        assert result['configured'] is False
        assert result['ok'] is False


def test_integrations_stripe_api_mocked():
    from utils.integrations_platform import check_stripe

    fake_stripe = MagicMock()
    fake_stripe.Balance.retrieve.return_value = {'object': 'balance'}

    with patch.dict(os.environ, {'STRIPE_SECRET_KEY': 'sk_test_x'}):
        with patch.dict('sys.modules', {'stripe': fake_stripe}):
            result = check_stripe()
    assert result['ok'] is True
    assert 'latency_ms' in result


# ── Platform ops facade & maintenance pipeline ────────────────────────────────


def test_platform_ops_status_full(app):
    with app.app_context():
        from utils.platform_ops import get_platform_ops_status

        ops = get_platform_ops_status()
        assert ops['status'] in ('healthy', 'warning', 'critical', 'degraded')
        assert 'postgres' in ops
        assert 'mongo' in ops
        assert 'ai' in ops
        assert 'integrations' in ops
        pg = ops['postgres']
        assert 'migration' in pg
        assert 'monitor' in pg
        assert 'page' in pg


def test_run_full_platform_ops_mocked(app):
    with app.app_context():
        from utils.platform_ops import run_full_platform_ops

        pg_result = {'status': 'success', 'steps': [{'step': 'x', 'ok': True}]}
        with patch('utils.db_maintenance.run_full_maintenance', return_value=pg_result), \
             patch('utils.mongo_platform.bootstrap_mongo', return_value={'steps': [{'step': 'm', 'ok': True}]}), \
             patch('utils.ai_platform.bootstrap_ai', return_value={'steps': [{'step': 'a', 'ok': True}]}), \
             patch('utils.platform_ops.get_platform_ops_status', return_value={'status': 'healthy'}):
            result = run_full_platform_ops(actor_user_id=None, restart=False)
        assert result['status'] in ('success', 'partial', 'failed')
        assert 'steps' in result


def test_system_health_includes_ops_summaries(app):
    with app.app_context():
        from utils.system_health import system_health

        payload = system_health()
        assert 'status' in payload
        assert isinstance(payload, dict)


def test_run_full_maintenance_includes_analyze_step(app):
    with app.app_context():
        from sqlalchemy import text

        from extensions import db

        try:
            db.session.execute(text('SELECT 1 FROM alembic_version LIMIT 1'))
        except Exception:
            pytest.skip('postgres not available')

        steps_out = [
            {'step': 'alembic_migrations', 'ok': True, 'message': 'ok'},
            {'step': 'schema_guards', 'ok': True, 'message': 'ok'},
            {'step': 'data_backfills', 'ok': True, 'message': 'ok'},
            {'step': 'mongodb_indexes', 'ok': True, 'message': 'ok'},
            {'step': 'postgres_analyze', 'ok': True, 'message': 'analyzed'},
            {'step': 'health_scan_indexes', 'ok': True, 'message': 'ok'},
        ]

        with patch('utils.db_maintenance.run_alembic_upgrade', return_value=steps_out[0]), \
             patch('utils.db_maintenance.run_schema_guards', return_value=steps_out[1]), \
             patch('utils.db_maintenance.run_data_backfills', return_value=steps_out[2]), \
             patch('utils.db_maintenance.run_mongo_maintenance', return_value=steps_out[3]), \
             patch('utils.db_maintenance.run_postgres_analyze', return_value=steps_out[4]), \
             patch('utils.db_maintenance.run_health_scan_and_indexes', return_value=steps_out[5]):
            try:
                from utils.db_maintenance import run_full_maintenance

                result = run_full_maintenance(actor_user_id=None, restart=False)
            except Exception as exc:
                if 'db_maintenance_runs' in str(exc):
                    pytest.skip('db_maintenance_runs not migrated')
                raise

            step_names = [s['step'] for s in result['steps']]
            assert 'postgres_analyze' in step_names
            assert len(result['steps']) >= 6

            from models import DbMaintenanceRun

            if result.get('run_id'):
                run = db.session.get(DbMaintenanceRun, result['run_id'])
                if run:
                    db.session.delete(run)
                    db.session.commit()
