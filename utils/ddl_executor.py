"""Execute PostgreSQL DDL safely (CONCURRENTLY for indexes during live traffic)."""
from __future__ import annotations

import logging
import os
import re

from sqlalchemy import text

logger = logging.getLogger(__name__)

_CREATE_INDEX_RE = re.compile(
    r'^CREATE\s+INDEX\s+(?:(?:CONCURRENTLY|IF\s+NOT\s+EXISTS)\s+)*',
    re.IGNORECASE,
)


def index_ddl_use_concurrently() -> bool:
    """Default on — use CONCURRENTLY for CREATE INDEX in production traffic."""
    env = os.getenv('FLASK_ENV', 'development').lower()
    if env in ('production', 'prod'):
        return True
    return os.getenv('DB_INDEX_USE_CONCURRENTLY', 'true').lower() in ('1', 'true', 'yes')


def prepare_postgres_ddl(ddl: str, *, use_concurrent: bool | None = None) -> tuple[str, bool]:
    """
    Return (sql, requires_autocommit).

  CONCURRENTLY indexes cannot run inside a transaction block.
    """
    sql = (ddl or '').strip().rstrip(';')
    if not sql:
        raise ValueError('Empty DDL')

    upper = sql.upper()
    if 'CREATE INDEX' not in upper:
        return sql, False

    use_concurrent = index_ddl_use_concurrently() if use_concurrent is None else use_concurrent
    if not use_concurrent or 'CONCURRENTLY' in upper:
        return sql, 'CONCURRENTLY' in upper

    if upper.startswith('CREATE INDEX IF NOT EXISTS '):
        sql = sql.replace('CREATE INDEX IF NOT EXISTS ', 'CREATE INDEX CONCURRENTLY IF NOT EXISTS ', 1)
    elif upper.startswith('CREATE INDEX '):
        sql = sql.replace('CREATE INDEX ', 'CREATE INDEX CONCURRENTLY ', 1)
    else:
        return sql, False

    return sql, True


def execute_postgres_ddl(engine, ddl: str, *, use_concurrent: bool | None = None) -> str:
    """Run DDL on a dedicated connection; returns executed SQL."""
    sql, autocommit = prepare_postgres_ddl(ddl, use_concurrent=use_concurrent)

    if autocommit:
        if engine.dialect.name != 'postgresql':
            with engine.connect() as conn:
                conn.execute(text(sql))
                conn.commit()
        else:
            with engine.connect().execution_options(isolation_level='AUTOCOMMIT') as conn:
                conn.execute(text(sql))
        logger.info('[ddl_executor] Applied (concurrent): %s', sql[:120])
    else:
        with engine.connect() as conn:
            conn.execute(text(sql))
            conn.commit()
        logger.debug('[ddl_executor] Applied: %s', sql[:120])

    return sql
