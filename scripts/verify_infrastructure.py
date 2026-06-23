#!/usr/bin/env python
"""Full infrastructure verification — imports, env docs, and key module checks."""
from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

os.environ.setdefault('REDIS_URI', 'memory://')
os.environ.setdefault('RUN_SCHEDULER', 'false')
os.environ.setdefault('EVENT_BUS_CONSUMER', 'false')
os.environ.setdefault('DB_BOOTSTRAP_ON_STARTUP', 'false')
os.environ.setdefault('SECRET_KEY', 'verify-check-key')
os.environ.setdefault('FLASK_ENV', 'development')

REQUIRED_FILES = (
    'Dockerfile',
    'DEPLOYMENT.md',
    'gunicorn.conf.py',
    'docker-compose.services.yml',
    'docker-compose.prod.yml',
    'docker-compose.observability.yml',
    '.env.production.example',
    'deploy/observability/prometheus.yml',
    'deploy/observability/alerts/trainiq.yml',
    'deploy/observability/alertmanager.yml',
    'scripts/run_web.py',
    'scripts/run_ops_worker.py',
    'scripts/production_preflight.py',
    'scripts/start_production.sh',
    'scripts/start_production.ps1',
    'scripts/load_smoke.py',
    'scripts/chaos_smoke.py',
    'utils/service_mode.py',
    'utils/event_bus.py',
    'utils/db_replica.py',
    'utils/ai_cache_storage.py',
    'utils/ops_auto_remediate.py',
    'utils/platform_ops_orchestrator.py',
    'utils/production_preflight.py',
)

REQUIRED_ENV_KEYS = (
    'SERVICE_MODE',
    'EVENT_BUS_ENABLED',
    'EVENT_BUS_CONSUMER',
    'DATABASE_READ_REPLICA_URL',
    'MONGO_READ_URI',
    'AI_CACHE_S3_BUCKET',
    'OPS_AUTO_REMEDIATE_SAFE',
    'PROMETHEUS_METRICS_ENABLED',
    'PROMETHEUS_METRICS_TOKEN',
)


def check_files() -> list[str]:
    errors = []
    for rel in REQUIRED_FILES:
        if not os.path.isfile(os.path.join(ROOT, rel)):
            errors.append(f'missing file: {rel}')
    return errors


def check_env_example() -> list[str]:
    errors = []
    path = os.path.join(ROOT, '.env.example')
    if not os.path.isfile(path):
        return ['missing .env.example']
    text = open(path, encoding='utf-8').read()
    for key in REQUIRED_ENV_KEYS:
        if f'{key}=' not in text:
            errors.append(f'.env.example missing {key}')
    return errors


def check_imports() -> list[str]:
    errors = []
    try:
        from utils.service_mode import (
            event_bus_consumer_enabled,
            register_lms_blueprints,
            register_platform_blueprints,
            service_mode,
        )

        assert service_mode() in ('full', 'web', 'platform')
        assert register_lms_blueprints() or register_platform_blueprints()
        _ = event_bus_consumer_enabled()
    except Exception as exc:
        errors.append(f'service_mode import failed: {exc}')

    try:
        from utils.event_bus import publish_agent_action, publish_health_cycle

        assert callable(publish_agent_action)
        assert callable(publish_health_cycle)
    except Exception as exc:
        errors.append(f'event_bus import failed: {exc}')

    try:
        from utils.platform_ops_orchestrator import queue_or_run_health_cycle

        assert callable(queue_or_run_health_cycle)
    except Exception as exc:
        errors.append(f'platform_ops_orchestrator import failed: {exc}')

    try:
        from app import app

        rules = {r.rule for r in app.url_map.iter_rules()}
        for required in ('/health', '/metrics', '/platform/dashboard', '/auth/login'):
            if required not in rules:
                errors.append(f'app missing route: {required}')
    except Exception as exc:
        errors.append(f'app import failed: {exc}')

    return errors


def main() -> int:
    errors: list[str] = []
    errors.extend(check_files())
    errors.extend(check_env_example())
    errors.extend(check_imports())

    if errors:
        print('Infrastructure verification FAILED:')
        for err in errors:
            print(f'  - {err}')
        return 1

    print('Infrastructure verification OK')
    print(f'  files: {len(REQUIRED_FILES)}')
    print(f'  env keys: {len(REQUIRED_ENV_KEYS)}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
