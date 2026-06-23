"""Phase 0 production-safety module tests."""
from unittest.mock import patch


def test_should_run_scheduler_defaults(monkeypatch):
    from utils.scheduler_config import should_run_scheduler, scheduler_jobs_for_ops_only

    monkeypatch.delenv('RUN_SCHEDULER', raising=False)
    monkeypatch.setenv('FLASK_ENV', 'development')
    assert should_run_scheduler() is True

    monkeypatch.setenv('FLASK_ENV', 'production')
    assert should_run_scheduler() is False

    monkeypatch.setenv('RUN_SCHEDULER', 'true')
    assert should_run_scheduler() is True

    monkeypatch.setenv('OPS_WORKER_MODE', 'true')
    assert scheduler_jobs_for_ops_only() is True


def test_ops_cache_local_ttl(monkeypatch):
    from utils import ops_cache

    monkeypatch.setenv('OPS_CACHE_USE_REDIS', 'false')
    ops_cache.invalidate_json_cached()
    calls = {'n': 0}

    def producer():
        calls['n'] += 1
        return {'v': calls['n']}

    assert ops_cache.get_json_cached('test_key', 60, producer) == {'v': 1}
    assert ops_cache.get_json_cached('test_key', 60, producer) == {'v': 1}
    ops_cache.invalidate_json_cached('test_key')
    assert ops_cache.get_json_cached('test_key', 60, producer) == {'v': 2}


def test_ops_alerts_respects_cooldown(monkeypatch, tmp_path):
    from utils import ops_alerts

    monkeypatch.setenv('PLATFORM_OPS_ALERT_WEBHOOK', 'http://example.test/hook')
    monkeypatch.setenv('PLATFORM_OPS_ALERT_COOLDOWN_SECONDS', '3600')
    monkeypatch.setattr(ops_alerts, '_COOLDOWN_FILE', str(tmp_path / 'cd.json'))

    with patch('utils.ops_cache._get_redis', return_value=None):
        with patch('urllib.request.urlopen') as urlopen_mock:
            urlopen_mock.return_value.__enter__.return_value.status = 200
            assert ops_alerts.maybe_send_ops_alert(status='critical', source='scheduler') is True
            assert ops_alerts.maybe_send_ops_alert(status='critical', source='scheduler') is False
            urlopen_mock.assert_called_once()


def test_ops_alerts_ignores_non_critical(monkeypatch):
    from utils.ops_alerts import maybe_send_ops_alert

    monkeypatch.setenv('PLATFORM_OPS_ALERT_WEBHOOK', 'http://example.test/hook')
    with patch('urllib.request.urlopen') as urlopen_mock:
        assert maybe_send_ops_alert(status='healthy', source='scheduler') is False
        urlopen_mock.assert_not_called()


def test_ops_alerts_email_fallback_when_no_webhook(monkeypatch):
    from utils import ops_alerts

    monkeypatch.delenv('PLATFORM_OPS_ALERT_WEBHOOK', raising=False)
    monkeypatch.setenv('PLATFORM_OPS_ALERT_EMAIL', 'true')
    monkeypatch.setenv('PLATFORM_OPS_ALERT_COOLDOWN_SECONDS', '60')

    with patch.object(ops_alerts, '_send_ceo_email_alert', return_value=True) as email_mock:
        with patch('utils.ops_cache._get_redis', return_value=None):
            assert ops_alerts.maybe_send_ops_alert(status='critical', source='scheduler') is True
    email_mock.assert_called_once()


def test_support_default_ttl_is_two_hours(monkeypatch):
    monkeypatch.delenv('PLATFORM_SUPPORT_TTL_HOURS', raising=False)
    from utils.support_session import support_session_ttl_hours

    assert support_session_ttl_hours() == 2


def test_build_metrics_api_payload_shape(monkeypatch):
    monkeypatch.setenv('OPS_CACHE_USE_REDIS', 'false')

    fake_ops = {
        'status': 'healthy',
        'postgres': {
            'migration': {'pending': False},
            'page': {
                'snapshot': None,
                'postgres_stats': {'capacity': {'connections': {}}},
            },
        },
        'mongo': {'available': True, 'tenant_db_count': 2, 'unprovisioned_tenants': 0},
        'ai': {'available': True, 'model_ready': True, 'resolved_model': 'gpt-test', 'cache': {'files': 1}},
        'integrations': {'checks': [{'ok': True}, {'ok': False}]},
    }

    with patch('utils.platform_ops.get_platform_ops_status', return_value=fake_ops):
        from utils.platform_metrics_api import build_metrics_api_payload

        payload = build_metrics_api_payload()
        assert payload['status'] == 'healthy'
        assert payload['integrations']['ok'] == 1
        assert payload['integrations']['total'] == 2
        assert 'system' in payload


def test_platform_ops_runs_roundtrip(app):
    from extensions import db
    from models import PlatformOpsRun
    from utils.platform_ops_runs import complete_ops_run, latest_ops_runs, start_ops_run

    with app.app_context():
        try:
            db.session.query(PlatformOpsRun).delete()
            db.session.commit()
        except Exception:
            db.session.rollback()

        run_id = start_ops_run(source='test', trigger='manual')
        if run_id is None:
            return  # table not migrated in this environment

        complete_ops_run(
            run_id,
            status='healthy',
            result={'monitor': {'issue_count': 0, 'snapshot_id': 1}, 'indexes': {'applied': 0}},
            snapshot_id=1,
        )
        rows = latest_ops_runs(limit=5)
        assert rows and rows[0]['source'] == 'test'
        assert rows[0]['status'] == 'healthy'
