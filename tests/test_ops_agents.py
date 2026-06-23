"""Tests for Platform Operations AI agents."""
from __future__ import annotations

import json
import os
from unittest.mock import patch

import pytest


@pytest.fixture
def platform_staff_client(app):
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    for lim in app.extensions.get("limiter") or ():
        lim.enabled = False

    from models import User
    from utils.platform_ceo import PLATFORM_CEO_EMAIL

    with app.app_context():
        user = User.query.filter(
            User.employee_email.ilike(PLATFORM_CEO_EMAIL)
        ).first()
        if not user:
            pytest.skip("Platform CEO user not in database")

    client = app.test_client()
    with client.session_transaction() as sess:
        sess["_user_id"] = str(user.id)
        sess["_fresh"] = True
        sess["tenant_id"] = user.tenant_id
    return client


def test_valid_domains():
    from utils.ops_agents import AGENT_META, VALID_DOMAINS

    assert VALID_DOMAINS == frozenset(AGENT_META.keys())
    assert 'postgres' in VALID_DOMAINS
    assert 'overview' in VALID_DOMAINS


def test_analyze_postgres_healthy():
    from utils.ops_agents import _analyze_postgres

    status, findings, actions, summary, score = _analyze_postgres({
        'migration_pending': False,
        'tables_ready': True,
        'issue_count': 0,
        'pending_recommendations': 0,
        'cache_hit_ratio': 0.99,
        'slow_queries': 0,
        'last_scan_at': '2026-01-01T00:00:00',
    })
    assert status == 'healthy'
    assert score >= 90
    assert any(a['id'] == 'scan' for a in actions)


def test_analyze_postgres_migration_pending():
    from utils.ops_agents import _analyze_postgres

    status, findings, _, _, _ = _analyze_postgres({
        'migration_pending': True,
        'tables_ready': True,
        'issue_count': 0,
        'pending_recommendations': 0,
    })
    assert status == 'warning'
    assert any('migration' in f['title'].lower() for f in findings)


def test_analyze_mongo_offline():
    from utils.ops_agents import _analyze_mongo

    status, findings, actions, summary, score = _analyze_mongo({
        'available': False,
        'reason': 'connection refused',
    })
    assert status == 'critical'
    assert score <= 30
    assert any(a['id'] == 'bootstrap' for a in actions)
    assert 'unavailable' in summary.lower()


def test_analyze_ai_cache_over_capacity():
    from utils.ops_agents import _analyze_ai

    status, findings, actions, _, _ = _analyze_ai({
        'status': 'warning',
        'available': True,
        'model_ready': True,
        'cache': {'over_capacity': True, 'total_mb': 600, 'expired': 0},
        'jobs': {'failed': 0},
        'latency': {},
    })
    assert status == 'warning'
    assert any(a['id'] == 'trim_cache' for a in actions)
    assert any('cache' in f['title'].lower() for f in findings)


def test_run_ops_agent_caches_report(app, tmp_path):
    with app.app_context():
        from utils import ops_agents

        cache_dir = tmp_path / 'ops_agents'
        with patch.object(ops_agents, 'CACHE_DIR', str(cache_dir)), \
             patch.object(ops_agents, 'USE_AI_DEFAULT', False), \
             patch.object(ops_agents, '_collect_postgres_context', return_value={
                 'migration_pending': False,
                 'tables_ready': True,
                 'issue_count': 0,
                 'pending_recommendations': 0,
                 'cache_hit_ratio': 0.97,
                 'slow_queries': 0,
                 'last_scan_at': '2026-01-01',
             }):
            report = ops_agents.run_ops_agent('postgres', force=True, use_ai=False)

        assert report['domain'] == 'postgres'
        assert report['agent_name'] == 'PostgreSQL Agent'
        assert report['status'] in ('healthy', 'warning', 'critical', 'degraded')
        cache_file = cache_dir / 'postgres.json'
        assert cache_file.is_file()
        with open(cache_file, encoding='utf-8') as fh:
            saved = json.load(fh)
        assert saved['domain'] == 'postgres'
        assert saved['summary'] == report['summary']


def test_execute_agent_action_unknown(app):
    with app.app_context():
        ok, msg = __import__('utils.ops_agents', fromlist=['execute_agent_action']).execute_agent_action(
            'postgres', 'not_a_real_action'
        )
    assert ok is False
    assert 'Unknown action' in msg


def test_execute_agent_action_refresh(app):
    with app.app_context():
        from utils.ops_agents import execute_agent_action

        with patch('utils.ops_agents.run_ops_agent') as mock_run:
            mock_run.return_value = {'status': 'healthy'}
            ok, msg = execute_agent_action('system', 'refresh')
        assert ok is True
        assert 'refreshed' in msg.lower()


def test_agents_api_route(platform_staff_client):
    resp = platform_staff_client.get('/platform/operations/agents-api')
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['ok'] is True
    assert isinstance(data['agents'], dict)


def test_operations_page_shows_agent_panel(platform_staff_client):
    resp = platform_staff_client.get('/platform/operations?tab=postgres')
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert 'PostgreSQL Agent' in html or 'Ops Agent' in html
    assert 'Refresh Agent' in html or 'Start Agent' in html
