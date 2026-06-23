"""Service mode route registration checks."""
from __future__ import annotations

import os
import subprocess
import sys


def _endpoints_for_mode(mode: str) -> set[str]:
    """Spawn isolated process to load app with a given SERVICE_MODE."""
    code = """
import os, json
os.environ.setdefault('REDIS_URI', 'memory://')
os.environ.setdefault('RUN_SCHEDULER', 'false')
os.environ.setdefault('EVENT_BUS_CONSUMER', 'false')
os.environ.setdefault('DB_BOOTSTRAP_ON_STARTUP', 'false')
os.environ.setdefault('SECRET_KEY', 'test-service-mode')
os.environ.setdefault('FLASK_ENV', 'development')
os.environ['SERVICE_MODE'] = %r
from app import app
print(json.dumps(sorted({r.endpoint for r in app.url_map.iter_rules()})))
""" % mode
    env = {**os.environ, 'SERVICE_MODE': mode, 'REDIS_URI': 'memory://'}
    result = subprocess.run(
        [sys.executable, '-c', code],
        capture_output=True,
        text=True,
        env=env,
        cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        timeout=120,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr or result.stdout)
    import json

    return set(json.loads(result.stdout.strip().splitlines()[-1]))


def test_full_mode_has_platform_and_lms():
    endpoints = _endpoints_for_mode('full')
    assert any(e.startswith('platform_routes.') for e in endpoints)
    assert any(e.startswith('study_material_routes.') for e in endpoints)
    assert 'auth_routes.login' in endpoints


def test_web_mode_excludes_platform():
    endpoints = _endpoints_for_mode('web')
    assert not any(e.startswith('platform_routes.') for e in endpoints)
    assert any(e.startswith('study_material_routes.') for e in endpoints)
    assert 'auth_routes.login' in endpoints


def test_platform_mode_has_platform_and_support_admin():
    endpoints = _endpoints_for_mode('platform')
    assert any(e.startswith('platform_routes.') for e in endpoints)
    assert any(e.startswith('admin_routes.') for e in endpoints)
    assert not any(e.startswith('study_material_routes.') for e in endpoints)
    assert not any(e.startswith('exams_routes.') for e in endpoints)
