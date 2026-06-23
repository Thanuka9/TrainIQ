"""Pre-deploy checks for production — env, connectivity, migrations."""
from __future__ import annotations

import logging
import os
import secrets
import sys

logger = logging.getLogger(__name__)

INSECURE_SECRETS = frozenset({
    '',
    'change-me-in-production',
    'fallback-secret-key',
    'test-secret-key',
    'ci-test-secret-key-not-for-production',
})


def is_production_env() -> bool:
    return os.getenv('FLASK_ENV', 'development').strip().lower() not in (
        'development',
        'dev',
        'local',
    )


def _check(name: str, ok: bool, detail: str, *, required: bool = True) -> dict:
    return {'name': name, 'ok': ok, 'detail': detail, 'required': required}


def check_env_vars() -> list[dict]:
    results = []
    prod = is_production_env()

    secret = (os.getenv('SECRET_KEY') or '').strip()
    secret_ok = len(secret) >= 32 and secret not in INSECURE_SECRETS
    results.append(_check(
        'SECRET_KEY',
        secret_ok,
        'set (32+ chars)' if secret_ok else 'must be a random 32+ character string',
    ))

    db_url = (os.getenv('DATABASE_URL') or '').strip()
    results.append(_check('DATABASE_URL', bool(db_url), 'set' if db_url else 'missing'))

    if prod:
        ceo_email = (os.getenv('TRAINIQ_CEO_EMAIL') or '').strip()
        results.append(_check('TRAINIQ_CEO_EMAIL', bool(ceo_email), 'set' if ceo_email else 'missing'))

        ceo_pw = (os.getenv('TRAINIQ_CEO_DEFAULT_PASSWORD') or '').strip()
        results.append(_check(
            'TRAINIQ_CEO_DEFAULT_PASSWORD',
            bool(ceo_pw),
            'set' if ceo_pw else 'required for CEO bootstrap in production',
        ))

        redis_uri = (os.getenv('REDIS_URI') or '').strip()
        redis_ok = bool(redis_uri) and not redis_uri.startswith('memory://')
        results.append(_check(
            'REDIS_URI',
            redis_ok,
            'real Redis URI required for multi-worker rate limits' if not redis_ok else 'set',
        ))

        secure = (os.getenv('SESSION_COOKIE_SECURE', 'True') or '').lower() in ('1', 'true', 'yes')
        results.append(_check(
            'SESSION_COOKIE_SECURE',
            secure,
            'true (HTTPS)' if secure else 'must be true behind HTTPS',
        ))

        if (os.getenv('PROMETHEUS_METRICS_ENABLED', '').lower() in ('1', 'true', 'yes')):
            token = (os.getenv('PROMETHEUS_METRICS_TOKEN') or '').strip()
            results.append(_check(
                'PROMETHEUS_METRICS_TOKEN',
                bool(token),
                'set when metrics enabled' if token else 'required when PROMETHEUS_METRICS_ENABLED=true',
            ))

        scheduler_on = (os.getenv('RUN_SCHEDULER', 'false').lower() in ('1', 'true', 'yes'))
        ops_worker = (os.getenv('OPS_WORKER_MODE', '').lower() in ('1', 'true', 'yes'))
        scheduler_ok = (not scheduler_on) or ops_worker
        results.append(_check(
            'RUN_SCHEDULER',
            scheduler_ok,
            'false on web workers (use ops-worker)' if scheduler_on and not ops_worker else 'ok',
        ))

        if (os.getenv('EVENT_BUS_ENABLED', '').lower() in ('1', 'true', 'yes')):
            results.append(_check(
                'EVENT_BUS_CONSUMER',
                (os.getenv('EVENT_BUS_CONSUMER', '').lower() in ('1', 'true', 'yes'))
                or ops_worker,
                'ops worker must consume events when bus enabled',
            ))

    mail_server = (os.getenv('MAIL_SERVER') or '').strip()
    results.append(_check(
        'MAIL_SERVER',
        bool(mail_server),
        'set' if mail_server else 'email (2FA, trials, invites) will not send',
        required=False,
    ))

    mongo_uri = (os.getenv('MONGO_URI') or '').strip()
    results.append(_check(
        'MONGO_URI',
        bool(mongo_uri),
        'set' if mongo_uri else 'file uploads / GridFS disabled',
        required=False,
    ))

    return results


def check_postgres() -> dict:
    try:
        import psycopg2

        psycopg2.connect(os.environ['DATABASE_URL']).close()
        return _check('postgres_connect', True, 'ok')
    except Exception as exc:
        return _check('postgres_connect', False, str(exc))


def check_redis() -> dict:
    uri = (os.getenv('REDIS_URI') or '').strip()
    if not uri or uri.startswith('memory://'):
        return _check('redis_connect', False, 'REDIS_URI not configured', required=is_production_env())
    try:
        import redis

        client = redis.from_url(uri, socket_connect_timeout=3)
        client.ping()
        return _check('redis_connect', True, 'ok')
    except Exception as exc:
        return _check('redis_connect', False, str(exc), required=is_production_env())


def check_mongodb() -> dict:
    try:
        from mongodb_operations import get_mongo_connection

        client, db, _ = get_mongo_connection()
        if client is None:
            return _check('mongodb_connect', False, 'unavailable', required=False)
        client.admin.command('ping')
        return _check('mongodb_connect', True, 'ok', required=False)
    except Exception as exc:
        return _check('mongodb_connect', False, str(exc), required=False)


def check_migrations() -> dict:
    try:
        os.environ.setdefault('REDIS_URI', os.getenv('REDIS_URI') or 'memory://')
        from app import app
        from flask_migrate import current as migrate_current
        from alembic.script import ScriptDirectory

        with app.app_context():
            config = app.extensions['migrate'].migrate.get_config()
            script = ScriptDirectory.from_config(config)
            head = script.get_current_head()
            cur = migrate_current()
            if cur is None:
                return _check('migrations', False, 'no alembic version — run flask db upgrade')
            if head and cur != head:
                return _check('migrations', False, f'pending migrations (db={cur}, head={head})')
            return _check('migrations', True, f'at head ({cur})')
    except Exception as exc:
        return _check('migrations', False, str(exc), required=False)


def run_preflight(*, skip_connectivity: bool = False, skip_migrations: bool = False) -> tuple[bool, list[dict]]:
    """Run all checks. Returns (all_required_passed, results)."""
    results: list[dict] = []
    results.extend(check_env_vars())

    if not skip_connectivity and (os.getenv('DATABASE_URL') or '').strip():
        results.append(check_postgres())
        results.append(check_redis())
        results.append(check_mongodb())

    if not skip_migrations and (os.getenv('DATABASE_URL') or '').strip():
        results.append(check_migrations())

    required_failed = [r for r in results if r.get('required', True) and not r['ok']]
    return len(required_failed) == 0, results


def generate_secret_key() -> str:
    return secrets.token_urlsafe(48)
