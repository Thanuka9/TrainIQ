"""Infrastructure — service split, event bus, replicas, cache backends."""
import json
import os
from unittest.mock import MagicMock, patch

import pytest


def test_service_mode_defaults(monkeypatch):
    monkeypatch.delenv('SERVICE_MODE', raising=False)
    from utils.service_mode import register_lms_blueprints, register_platform_blueprints, service_mode

    assert service_mode() == 'full'
    assert register_lms_blueprints() is True
    assert register_platform_blueprints() is True


def test_service_mode_web(monkeypatch):
    monkeypatch.setenv('SERVICE_MODE', 'web')
    from importlib import reload
    import utils.service_mode as sm

    reload(sm)
    assert sm.register_lms_blueprints() is True
    assert sm.register_platform_blueprints() is False
    assert sm.register_support_admin_blueprints() is False


def test_service_mode_platform(monkeypatch):
    monkeypatch.setenv('SERVICE_MODE', 'platform')
    from importlib import reload
    import utils.service_mode as sm

    reload(sm)
    assert sm.register_lms_blueprints() is False
    assert sm.register_platform_blueprints() is True
    assert sm.register_support_admin_blueprints() is True


def test_event_bus_publish_disabled(monkeypatch):
    monkeypatch.setenv('EVENT_BUS_ENABLED', 'false')
    from utils.event_bus import publish_ops_event

    assert publish_ops_event('test', {'a': 1}) is None


def test_event_bus_dispatch_agent_action(app):
    with app.app_context():
        from utils.event_bus import _dispatch_event

        with patch('utils.ops_agents.execute_agent_action_sync', return_value=(True, 'ok')) as sync:
            _dispatch_event(
                {
                    'type': 'ops.agent_action',
                    'payload': json.dumps({'domain': 'postgres', 'action_id': 'noop', 'actor_user_id': 1}),
                }
            )
            sync.assert_called_once()


def test_execute_agent_action_queues_when_bus_enabled(app, monkeypatch):
    monkeypatch.setenv('EVENT_BUS_ENABLED', 'true')
    with app.app_context():
        from utils.ops_agents import execute_agent_action

        with patch('utils.event_bus.event_bus_enabled', return_value=True):
            with patch('utils.event_bus.publish_agent_action', return_value='1-0') as pub:
                ok, msg = execute_agent_action('postgres', 'refresh', actor_user_id=1)
                assert ok is True
                assert 'queued' in msg.lower()
                pub.assert_called_once()


def test_db_replica_bind_configured(app, monkeypatch):
    monkeypatch.setenv('DATABASE_READ_REPLICA_URL', 'postgresql://reader@localhost/replica')
    from utils.db_replica import configure_sqlalchemy_binds, read_replica_configured

    assert read_replica_configured() is True
    configure_sqlalchemy_binds(app)
    assert 'analytics' in app.config['SQLALCHEMY_BINDS']


def test_using_analytics_bind_no_replica(app):
    with app.app_context():
        from models import User
        from utils.db_replica import using_analytics_bind

        q = using_analytics_bind(User.query)
        assert q is not None


def test_disk_cache_storage_roundtrip(tmp_path):
    from utils.ai_cache_storage import DiskCacheStorage

    store = DiskCacheStorage(str(tmp_path))
    store.write('abc', {'v': 1, 'ts': 123})
    assert store.read('abc') == {'v': 1, 'ts': 123}
    assert 'abc' in store.list_keys()
    assert store.delete('abc') is True
    assert store.read('abc') is None


def test_get_cache_storage_defaults_disk(monkeypatch):
    monkeypatch.delenv('AI_CACHE_S3_BUCKET', raising=False)
    import utils.ai_cache_storage as mod

    mod._storage = None
    storage = mod.get_cache_storage()
    assert storage.describe()['backend'] == 'disk'


def test_auto_remediate_disabled_by_default(monkeypatch):
    monkeypatch.delenv('OPS_AUTO_REMEDIATE_SAFE', raising=False)
    from utils.ops_auto_remediate import auto_remediate_enabled, maybe_auto_remediate_after_scan

    assert auto_remediate_enabled() is False
    assert maybe_auto_remediate_after_scan({'issue_count': 5}) is None


def test_mongo_read_preference_mapping():
    from mongodb_operations import _mongo_read_preference
    from pymongo import ReadPreference

    assert _mongo_read_preference() == ReadPreference.PRIMARY


def test_platform_analytics_ro_helper(app):
    with app.app_context():
        from models import Tenant
        from utils.platform_analytics import _ro

        assert _ro(Tenant) is not None


def test_purge_tenant_storage_empty_tenant(app):
    with app.app_context():
        from utils.tenant_gdpr import purge_tenant_storage

        with patch('utils.mongo_tenant.get_tenant_database') as gtd:
            gfs = MagicMock()
            gfs.find.return_value = []
            gtd.return_value = MagicMock()
            with patch('gridfs.GridFS', return_value=gfs):
                stats = purge_tenant_storage(999999)
        assert 'gridfs_files' in stats
        assert stats['gridfs_files'] == 0


def test_queue_or_run_health_cycle_sync(app):
    with app.app_context():
        from utils.platform_ops_orchestrator import queue_or_run_health_cycle

        with patch('utils.event_bus.event_bus_enabled', return_value=False):
            with patch('utils.platform_ops_orchestrator.run_health_cycle', return_value={'status': 'healthy'}) as run:
                result = queue_or_run_health_cycle(source='ceo_scan', apply_safe=False)
        assert result['status'] == 'healthy'
        run.assert_called_once()


def test_queue_or_run_health_cycle_queues(app, monkeypatch):
    monkeypatch.setenv('EVENT_BUS_ENABLED', 'true')
    with app.app_context():
        from utils.platform_ops_orchestrator import queue_or_run_health_cycle

        with patch('utils.event_bus.event_bus_enabled', return_value=True):
            with patch('utils.service_mode.is_ops_worker_process', return_value=False):
                with patch('utils.event_bus.publish_health_cycle', return_value='1-0') as pub:
                    result = queue_or_run_health_cycle(source='ceo_apply', apply_safe=True)
        assert result.get('queued') is True
        pub.assert_called_once()


def test_purge_deletes_tenant_scoped_models(app):
    with app.app_context():
        from utils.tenant_gdpr import _delete_tenant_rows
        from models import Announcement

        with patch('utils.tenant_gdpr._delete_tenant_rows', wraps=_delete_tenant_rows) as delete_mock:
            with patch('utils.mongo_tenant.get_tenant_database') as gtd:
                gfs = MagicMock()
                gfs.find.return_value = []
                gtd.return_value = MagicMock()
                with patch('gridfs.GridFS', return_value=gfs):
                    with patch.object(Announcement.query, 'filter_by') as fb:
                        chain = MagicMock()
                        chain.delete.return_value = 0
                        fb.return_value = chain
                        from utils.tenant_gdpr import purge_tenant_storage

                        purge_tenant_storage(999999)
        assert delete_mock.called


def test_stripe_webhook_failed_metric(app, client):
    with patch('billing_routes.handle_webhook_payload', return_value=None):
        with patch('utils.prometheus_metrics.inc_stripe_webhook') as inc:
            resp = client.post('/webhooks/stripe', data=b'{}')
    assert resp.status_code == 400
    inc.assert_called_once_with('unknown', 'failed')


def test_event_bus_health_cycle_dispatch(app):
    with app.app_context():
        from utils.event_bus import _dispatch_event

        with patch('utils.platform_ops_orchestrator.run_health_cycle') as run:
            _dispatch_event(
                {
                    'type': 'ops.health_cycle',
                    'payload': json.dumps({'source': 'event_bus', 'apply_safe': True, 'actor_user_id': 1}),
                }
            )
            run.assert_called_once_with(
                source='event_bus',
                apply_safe=True,
                blocking_lock=True,
                actor_user_id=1,
            )
