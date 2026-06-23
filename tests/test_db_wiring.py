"""Verify DB platform module wiring."""
from __future__ import annotations


def test_migration_chain_head():
    from alembic.script import ScriptDirectory
    from flask import Flask
    from flask_migrate import Migrate

    from extensions import db

    app = Flask(__name__)
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    db.init_app(app)
    Migrate(app, db, directory='migrations')

    with app.app_context():
        script = ScriptDirectory.from_config(app.extensions['migrate'].migrate.get_config())
        heads = script.get_heads()
        assert heads == ['e4f5a6b7c8d9'], f'unexpected migration head(s): {heads}'


def test_model_tables_match_migrations(app):
    with app.app_context():
        from models import (
            DbMaintenanceRun,
            DbMetricSample,
            DbOptimizationRecommendation,
            DbPerformanceSnapshot,
            PlatformOpsRun,
        )

        assert DbPerformanceSnapshot.__tablename__ == 'db_performance_snapshots'
        assert DbOptimizationRecommendation.__tablename__ == 'db_optimization_recommendations'
        assert DbMaintenanceRun.__tablename__ == 'db_maintenance_runs'
        assert PlatformOpsRun.__tablename__ == 'platform_ops_runs'
        assert DbMetricSample.__tablename__ == 'db_metric_samples'


def test_catalog_indexes_in_performance_ddl():
    from utils.db_catalog import PERFORMANCE_INDEX_DDL, SQL_OPTIMIZATION_CATALOG

    ddl_blob = '\n'.join(PERFORMANCE_INDEX_DDL)
    for spec in SQL_OPTIMIZATION_CATALOG:
        if spec.tier == 'safe' and spec.index_name:
            assert spec.index_name in ddl_blob


def test_platform_db_health_routes_registered(app):
    rules = {rule.rule for rule in app.url_map.iter_rules()}
    for path in (
        '/platform/operations',
        '/platform/db-health',
        '/platform/db-health/run-full',
        '/platform/operations/run',
        '/platform/operations/run-full',
        '/platform/operations/apply-safe',
        '/platform/security/totp',
        '/platform/operations/mongo/run',
        '/platform/operations/ai/clear-cache',
        '/platform/operations/ai/refresh',
    ):
        assert path in rules


def test_platform_ops_modules(app):
    with app.app_context():
        from utils.mongo_platform import collect_mongo_ops_status
        from utils.ai_platform import get_ai_ops_status
        from utils.integrations_platform import get_integrations_status
        from utils.platform_ops import get_platform_ops_status

        integrations = get_integrations_status()
        assert 'checks' in integrations
        ai = get_ai_ops_status()
        assert 'engine' in ai
        mongo = collect_mongo_ops_status()
        assert 'available' in mongo
        ops = get_platform_ops_status()
        assert 'postgres' in ops and 'mongo' in ops and 'ai' in ops


def test_db_platform_exports(app):
    with app.app_context():
        from utils import db_platform

        assert callable(db_platform.bootstrap_database)
        assert callable(db_platform.ensure_database_healthy)
        assert callable(db_platform.run_full_maintenance)
        assert callable(db_platform.get_ops_status)

        status = db_platform.get_ops_status()
        assert 'migration' in status
        assert 'monitor' in status


def test_load_db_health_page_data_shape(app):
    with app.app_context():
        from utils.db_maintenance import load_db_health_page_data

        page = load_db_health_page_data()
        assert 'snapshot' in page
        assert 'tables_ready' in page


def test_analyze_tables_in_catalog():
    from utils.db_catalog import ANALYZE_TABLES, PERFORMANCE_INDEX_DDL

    ddl_tables = set()
    for ddl in PERFORMANCE_INDEX_DDL:
        if ' ON ' in ddl:
            ddl_tables.add(ddl.split(' ON ', 1)[1].split('(', 1)[0].strip())
    for table in ANALYZE_TABLES:
        assert table in ddl_tables or table in (
            'users', 'tenants', 'notifications', 'user_scores', 'audit_log',
            'support_tickets', 'course_notes', 'exams', 'study_materials',
            'billing_events', 'tenant_invites', 'announcements', 'tasks',
        )


def test_mongo_catalog_compound_indexes():
    from utils.mongo_catalog import MONGO_COMPOUND_INDEX_CATALOG, MONGO_INDEX_CATALOG

    assert len(MONGO_INDEX_CATALOG) >= 4
    assert len(MONGO_COMPOUND_INDEX_CATALOG) >= 2
    for spec in MONGO_COMPOUND_INDEX_CATALOG:
        assert len(spec.fields) >= 2
        assert spec.name


def test_ai_cache_stats_shape(tmp_path, monkeypatch):
    from utils import ai_cache

    monkeypatch.setattr(ai_cache, 'CACHE_DIR', str(tmp_path))
    stats = ai_cache.get_cache_stats()
    assert 'files' in stats
    assert 'max_mb' in stats
    assert 'over_capacity' in stats


def test_ops_constants_defaults():
    from utils.ops_constants import AI_CACHE_MAX_MB, MONGO_PROVISION_WORKERS

    assert AI_CACHE_MAX_MB > 0
    assert MONGO_PROVISION_WORKERS >= 1
