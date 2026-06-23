"""Startup database bootstrap policy (production: deploy-only)."""
from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)


def should_bootstrap_on_startup() -> bool:
    explicit = (os.getenv('DB_BOOTSTRAP_ON_STARTUP') or '').strip().lower()
    if explicit in ('1', 'true', 'yes'):
        return True
    if explicit in ('0', 'false', 'no'):
        return False
    return os.getenv('FLASK_ENV', 'development') == 'development'


def run_startup_database_check() -> None:
    """Log migration drift without running schema guards on every web worker."""
    try:
        from utils.db_maintenance import get_migration_status

        status = get_migration_status()
        if status.get('pending'):
            logger.warning(
                '[startup] Pending Alembic migrations — run deploy bootstrap '
                '(scripts/push_databases.py or DB_BOOTSTRAP_ON_STARTUP=true once).'
            )
    except Exception as exc:
        logger.debug('[startup] migration check skipped: %s', exc)
