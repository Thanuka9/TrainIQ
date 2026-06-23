"""Apply idempotent schema guards from the central DB catalog."""
from __future__ import annotations

import logging
import os

from utils.db_catalog import all_schema_ddl

logger = logging.getLogger(__name__)


def schema_guards_frozen() -> bool:
    """In production, guards are frozen — new schema changes must use Alembic only."""
    explicit = (os.getenv('SCHEMA_GUARDS_FROZEN') or '').strip().lower()
    if explicit in ('0', 'false', 'no'):
        return False
    if explicit in ('1', 'true', 'yes'):
        return True
    return os.getenv('FLASK_ENV', 'development').lower() in ('production', 'prod')


def _is_create_index(sql: str) -> bool:
    return (sql or '').strip().upper().startswith('CREATE INDEX')


def apply_startup_schema_guards(*, force: bool = False) -> dict:
    """Apply idempotent column and index DDL. Returns {applied, skipped, errors}."""
    if schema_guards_frozen() and not force:
        logger.info('[schema_guards] Frozen — skipping runtime DDL (use Alembic migrations)')
        return {
            'applied': 0,
            'skipped': 0,
            'errors': [],
            'frozen': True,
            'message': 'Schema guards frozen in production. Use Alembic migrations for new columns.',
        }

    from extensions import db
    from utils.db_maintenance_lock import platform_maintenance_lock
    from utils.ddl_executor import execute_postgres_ddl

    applied = 0
    skipped = 0
    errors: list[str] = []

    with platform_maintenance_lock(blocking=True):
        engine = db.engine
        for sql in all_schema_ddl():
            try:
                if _is_create_index(sql):
                    execute_postgres_ddl(engine, sql)
                else:
                    from sqlalchemy import text

                    with engine.connect() as conn:
                        conn.execute(text(sql))
                        conn.commit()
                applied += 1
            except Exception as exc:
                skipped += 1
                errors.append(f"{sql[:72]}… — {exc}")

    return {'applied': applied, 'skipped': skipped, 'errors': errors, 'frozen': False}
