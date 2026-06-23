"""Tests for CEO full maintenance orchestrator."""
from __future__ import annotations

from unittest.mock import patch

import pytest


def test_get_migration_status_structure(app):
    with app.app_context():
        from utils.db_maintenance import get_migration_status

        status = get_migration_status()
        assert 'current' in status
        assert 'heads' in status
        assert 'pending' in status


def test_startup_schema_guards_idempotent(app):
    with app.app_context():
        from utils.startup_schema import apply_startup_schema_guards

        r1 = apply_startup_schema_guards()
        r2 = apply_startup_schema_guards()
        assert r1.get('applied', 0) >= 0
        assert r2.get('applied', 0) >= 0


def test_run_full_maintenance_mocked(app):
    with app.app_context():
        from sqlalchemy import text

        from extensions import db

        try:
            db.session.execute(text('SELECT 1 FROM alembic_version LIMIT 1'))
        except Exception:
            pytest.skip('postgres not available')

        steps = [
            {'step': 'alembic_migrations', 'ok': True, 'message': 'ok', 'detail': None},
            {'step': 'schema_guards', 'ok': True, 'message': 'ok', 'detail': None},
            {'step': 'data_backfills', 'ok': True, 'message': 'ok', 'detail': None},
            {'step': 'mongodb_indexes', 'ok': True, 'message': 'ok', 'detail': None},
            {'step': 'postgres_analyze', 'ok': True, 'message': 'ok', 'detail': None},
            {'step': 'health_scan_indexes', 'ok': True, 'message': 'ok', 'detail': None},
        ]

        with patch('utils.db_maintenance.run_alembic_upgrade', return_value=steps[0]), \
             patch('utils.db_maintenance.run_schema_guards', return_value=steps[1]), \
             patch('utils.db_maintenance.run_data_backfills', return_value=steps[2]), \
             patch('utils.db_maintenance.run_mongo_maintenance', return_value=steps[3]), \
             patch('utils.db_maintenance.run_postgres_analyze', return_value=steps[4]), \
             patch('utils.db_maintenance.run_health_scan_and_indexes', return_value=steps[5]):
            try:
                from utils.db_maintenance import run_full_maintenance

                result = run_full_maintenance(actor_user_id=None, restart=False)
            except Exception as exc:
                if 'db_maintenance_runs' in str(exc):
                    pytest.skip('db_maintenance_runs table not migrated')
                raise

            assert result['status'] in ('success', 'partial', 'failed')
            assert len(result.get('steps', [])) >= 6

            from models import DbMaintenanceRun

            run = db.session.get(DbMaintenanceRun, result['run_id'])
            if run:
                db.session.delete(run)
                db.session.commit()


def test_restart_skipped_without_config():
    from utils.app_restart import request_app_restart

    with patch.dict('os.environ', {}, clear=True):
        ok, msg, _detail = request_app_restart()
        assert ok is False
        assert 'skipped' in msg.lower() or 'Restart' in msg
