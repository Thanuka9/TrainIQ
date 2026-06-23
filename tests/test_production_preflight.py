"""Production preflight checks."""
import os

import pytest


def test_generate_secret_key_length():
    from utils.production_preflight import generate_secret_key

    key = generate_secret_key()
    assert len(key) >= 32
    assert key not in ('', 'change-me-in-production', 'fallback-secret-key')


def test_env_checks_development(monkeypatch):
    monkeypatch.setenv('FLASK_ENV', 'development')
    monkeypatch.setenv('SECRET_KEY', 'x' * 40)
    monkeypatch.setenv('DATABASE_URL', 'postgresql://localhost/test')

    from utils.production_preflight import check_env_vars

    results = {r['name']: r for r in check_env_vars()}
    assert results['SECRET_KEY']['ok'] is True
    assert results['DATABASE_URL']['ok'] is True
    assert 'TRAINIQ_CEO_EMAIL' not in results


def test_env_checks_production_missing_redis(monkeypatch):
    monkeypatch.setenv('FLASK_ENV', 'production')
    monkeypatch.setenv('SECRET_KEY', 'x' * 40)
    monkeypatch.setenv('DATABASE_URL', 'postgresql://localhost/test')
    monkeypatch.setenv('TRAINIQ_CEO_EMAIL', 'ceo@test.com')
    monkeypatch.setenv('TRAINIQ_CEO_DEFAULT_PASSWORD', 'pw')
    monkeypatch.setenv('REDIS_URI', 'memory://')
    monkeypatch.setenv('SESSION_COOKIE_SECURE', 'true')

    from utils.production_preflight import check_env_vars

    results = {r['name']: r for r in check_env_vars()}
    assert results['REDIS_URI']['ok'] is False
    assert results['SESSION_COOKIE_SECURE']['ok'] is True


def test_run_preflight_skips_connectivity(monkeypatch):
    monkeypatch.setenv('FLASK_ENV', 'development')
    monkeypatch.setenv('SECRET_KEY', 'x' * 40)
    monkeypatch.setenv('DATABASE_URL', 'postgresql://localhost/test')

    from utils.production_preflight import run_preflight

    ok, results = run_preflight(skip_connectivity=True, skip_migrations=True)
    names = {r['name'] for r in results}
    assert 'postgres_connect' not in names
    assert 'migrations' not in names
    assert ok is True


def test_security_rejects_memory_redis_in_production(monkeypatch):
    monkeypatch.setenv('FLASK_ENV', 'production')
    monkeypatch.setenv('TRAINIQ_CEO_EMAIL', 'ceo@test.com')
    monkeypatch.setenv('REDIS_URI', 'memory://')

    from flask import Flask
    from utils.security import validate_production_config

    app = Flask(__name__)
    app.config['SECRET_KEY'] = 'a' * 40
    with pytest.raises(RuntimeError, match='REDIS_URI'):
        validate_production_config(app)


def test_system_health_includes_redis(app, monkeypatch):
    monkeypatch.setenv('REDIS_URI', 'memory://')
    with app.app_context():
        from utils.system_health import system_health

        payload = system_health()
        assert 'redis' in payload
        assert payload['redis']['ok'] is False
