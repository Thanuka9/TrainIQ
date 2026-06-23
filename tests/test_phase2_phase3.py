"""Phase 2 metrics and Phase 3 schema policy tests."""
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

import pytest


def test_probe_cooldown_skips_fresh_snapshot(monkeypatch):
    monkeypatch.setenv('OPS_PROBE_MIN_INTERVAL_MINUTES', '30')

    with patch('utils.snapshot_read.snapshot_age_seconds', return_value=120.0):
        from utils.ops_probe_schedule import should_collect_fresh_probe

        allowed, reason = should_collect_fresh_probe(force=False)
    assert allowed is False
    assert reason == 'probe_cooldown'


def test_probe_forced_bypasses_cooldown(monkeypatch):
    with patch('utils.snapshot_read.snapshot_age_seconds', return_value=10.0):
        from utils.ops_probe_schedule import should_collect_fresh_probe

        allowed, _ = should_collect_fresh_probe(force=True)
    assert allowed is True


def test_ops_agents_defer_after_monitor(monkeypatch):
    monkeypatch.setenv('OPS_AGENTS_DELAY_AFTER_MONITOR_MINUTES', '5')

    with patch('utils.snapshot_read.snapshot_age_seconds', return_value=60.0):
        from utils.ops_probe_schedule import skip_ops_agents_refresh

        defer, reason = skip_ops_agents_refresh()
    assert defer is True
    assert reason == 'awaiting_post_monitor_delay'


def test_peak_hour_blocks_scheduled_maintenance(monkeypatch):
    monkeypatch.setenv('PLATFORM_PEAK_GUARD_ENABLED', 'true')
    monkeypatch.setenv('PLATFORM_PEAK_HOURS', '9-17')
    monkeypatch.setenv('PLATFORM_PEAK_TZ', 'UTC')

    noon = datetime(2026, 6, 15, 12, 0, 0, tzinfo=__import__('datetime').timezone.utc)
    from utils import maintenance_window as mw

    with patch.object(mw, 'datetime') as dt_mock:
        dt_mock.now.return_value = noon
        from utils.maintenance_window import is_peak_traffic_window, scheduled_maintenance_allowed

        assert is_peak_traffic_window(noon) is True
        allowed, reason = scheduled_maintenance_allowed(manual=False, source='scheduler')
        assert allowed is False
        assert reason == 'peak_hours'


def test_ceo_maintenance_bypasses_peak_hour(monkeypatch):
    monkeypatch.setenv('PLATFORM_PEAK_GUARD_ENABLED', 'true')
    from utils.maintenance_window import scheduled_maintenance_allowed

    allowed, reason = scheduled_maintenance_allowed(manual=True, source='ceo_maintenance')
    assert allowed is True
    assert reason == 'manual'


def test_bootstrap_on_startup_default_production(monkeypatch):
    monkeypatch.setenv('FLASK_ENV', 'production')
    monkeypatch.delenv('DB_BOOTSTRAP_ON_STARTUP', raising=False)
    from utils.startup_bootstrap import should_bootstrap_on_startup

    assert should_bootstrap_on_startup() is False


def test_bootstrap_on_startup_development(monkeypatch):
    monkeypatch.setenv('FLASK_ENV', 'development')
    monkeypatch.delenv('DB_BOOTSTRAP_ON_STARTUP', raising=False)
    from utils.startup_bootstrap import should_bootstrap_on_startup

    assert should_bootstrap_on_startup() is True


def test_record_metric_samples_from_report():
    from utils.db_metric_samples import _extract_metrics

    report = {
        'issue_count': 2,
        'postgres': {'capacity': {'cache_hit_ratio': 0.99, 'database_size_mb': 100, 'connections': {'active': 3, 'max': 100}}},
        'mongo': {'tenant_db_count': 4, 'server': {'total_storage_mb': 50}},
    }
    metrics = dict(_extract_metrics(report))
    assert metrics['pg.cache_hit_ratio'] == 0.99
    assert metrics['mongo.tenant_db_count'] == 4


def test_snapshot_read_empty_payload():
    with patch('utils.snapshot_read.load_latest_snapshot_row', return_value=None):
        from utils.snapshot_read import load_latest_snapshot_payload

        payload = load_latest_snapshot_payload()
    assert payload['tables_ready'] is False
    assert payload['snapshot_id'] is None


def test_schema_guards_deferred_in_peak(monkeypatch):
    monkeypatch.setenv('SCHEMA_GUARDS_ENABLED', 'true')

    with patch('utils.maintenance_window.scheduled_maintenance_allowed', return_value=(False, 'peak_hours')):
        from utils.db_maintenance import run_schema_guards

        step = run_schema_guards(manual=False)
    assert step['step'] == 'schema_guards'
    assert step.get('detail', {}).get('skipped') is True


def test_schema_guards_frozen_in_production(monkeypatch):
    monkeypatch.setenv('FLASK_ENV', 'production')
    monkeypatch.delenv('SCHEMA_GUARDS_FROZEN', raising=False)
    from utils.startup_schema import apply_startup_schema_guards, schema_guards_frozen

    assert schema_guards_frozen() is True
    result = apply_startup_schema_guards()
    assert result.get('frozen') is True
    assert result.get('applied') == 0


def test_snapshot_max_count_default(monkeypatch):
    monkeypatch.delenv('DB_SNAPSHOT_MAX_COUNT', raising=False)
    from utils.snapshot_retention import snapshot_max_count

    assert snapshot_max_count() == 500


def test_probe_default_interval_fifteen_minutes(monkeypatch):
    monkeypatch.delenv('OPS_PROBE_MIN_INTERVAL_MINUTES', raising=False)
    from utils.ops_probe_schedule import probe_min_interval_minutes

    assert probe_min_interval_minutes() == 15


def test_ops_trend_bundle_keys():
    from utils.db_metric_samples import ops_trend_bundle

    bundle = ops_trend_bundle(limit=5)
    assert 'pg.cache_hit_ratio' in bundle
    assert 'pg.issue_count' in bundle
