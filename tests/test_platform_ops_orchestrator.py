"""Tests for unified platform health cycle orchestrator."""
from contextlib import contextmanager
from unittest.mock import patch


@contextmanager
def _lock_acquired(**_kwargs):
    yield True


@contextmanager
def _lock_busy(**_kwargs):
    yield False


def test_scheduler_respects_env_for_apply(monkeypatch):
    monkeypatch.setenv('DB_OPTIMIZER_AUTO_APPLY', 'false')

    with patch('utils.db_maintenance_lock.platform_maintenance_lock', _lock_acquired):
        with patch('utils.db_optimizer_agent.run_monitor_cycle') as scan_mock:
            scan_mock.return_value = {'status': 'healthy', 'issue_count': 0, 'snapshot_id': 1}
            with patch('utils.db_optimizer_agent.apply_all_safe_recommendations') as apply_mock:
                with patch('utils.platform_ops.invalidate_ops_read_caches'):
                    with patch('utils.platform_ops_runs.start_ops_run', return_value=1):
                        with patch('utils.platform_ops_runs.complete_ops_run'):
                            with patch('utils.ops_alerts.maybe_send_ops_alert'):
                                from utils.platform_ops_orchestrator import run_health_cycle

                                run_health_cycle(source='scheduler', apply_safe=True, blocking_lock=False)
                apply_mock.assert_not_called()


def test_cli_apply_safe_runs_without_env(monkeypatch):
    monkeypatch.setenv('DB_OPTIMIZER_AUTO_APPLY', 'false')

    with patch('utils.db_maintenance_lock.platform_maintenance_lock', _lock_acquired):
        with patch('utils.db_optimizer_agent.run_monitor_cycle') as scan_mock:
            scan_mock.return_value = {'status': 'healthy', 'issue_count': 0, 'snapshot_id': 9}
            with patch('utils.db_optimizer_agent.apply_all_safe_recommendations') as apply_mock:
                apply_mock.return_value = {'applied': 2, 'failed': 0, 'skipped': 0}
                with patch('utils.platform_ops.invalidate_ops_read_caches'):
                    with patch('utils.platform_ops_runs.start_ops_run', return_value=1):
                        with patch('utils.platform_ops_runs.complete_ops_run'):
                            with patch('utils.ops_alerts.maybe_send_ops_alert'):
                                from utils.platform_ops_orchestrator import run_health_cycle

                                result = run_health_cycle(source='ceo_apply', apply_safe=True, blocking_lock=True)
                apply_mock.assert_called_once_with(9)
                assert result['indexes']['applied'] == 2


def test_ceo_maintenance_applies_without_env(monkeypatch):
    monkeypatch.setenv('DB_OPTIMIZER_AUTO_APPLY', 'false')

    with patch('utils.db_maintenance_lock.platform_maintenance_lock', _lock_acquired):
        with patch('utils.db_optimizer_agent.run_monitor_cycle') as scan_mock:
            scan_mock.return_value = {'status': 'healthy', 'issue_count': 0, 'snapshot_id': 3}
            with patch('utils.db_optimizer_agent.apply_all_safe_recommendations') as apply_mock:
                apply_mock.return_value = {'applied': 1, 'failed': 0, 'skipped': 0}
                with patch('utils.platform_ops.invalidate_ops_read_caches'):
                    with patch('utils.platform_ops_runs.start_ops_run', return_value=1):
                        with patch('utils.platform_ops_runs.complete_ops_run'):
                            with patch('utils.ops_alerts.maybe_send_ops_alert'):
                                from utils.platform_ops_orchestrator import run_health_cycle

                                result = run_health_cycle(source='ceo_maintenance', apply_safe=True)
                apply_mock.assert_called_once_with(3)
                assert result['indexes']['applied'] == 1


def test_skips_when_lock_busy():
    with patch('utils.db_maintenance_lock.platform_maintenance_lock', _lock_busy):
        with patch('utils.platform_ops_runs.start_ops_run', return_value=1):
            with patch('utils.platform_ops_runs.complete_ops_run') as complete_mock:
                from utils.platform_ops_orchestrator import run_health_cycle

                result = run_health_cycle(source='scheduler', apply_safe=False)
                assert result['skipped'] is True
                complete_mock.assert_called_once()
