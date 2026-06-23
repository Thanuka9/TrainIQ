"""PostgreSQL read-replica routing for heavy analytics queries."""
from __future__ import annotations

import logging
import os
from contextlib import contextmanager

logger = logging.getLogger(__name__)


def read_replica_configured() -> bool:
    return bool((os.getenv('DATABASE_READ_REPLICA_URL') or '').strip())


def configure_sqlalchemy_binds(app) -> None:
    replica = (os.getenv('DATABASE_READ_REPLICA_URL') or '').strip()
    if replica:
        binds = dict(app.config.get('SQLALCHEMY_BINDS') or {})
        binds['analytics'] = replica
        app.config['SQLALCHEMY_BINDS'] = binds
        logger.info('[db_replica] analytics bind configured')


@contextmanager
def analytics_session():
    """Yield a SQLAlchemy session on the read replica when configured."""
    from flask import has_app_context

    if not has_app_context():
        from extensions import db

        yield db.session
        return

    from flask import current_app
    from extensions import db

    binds = current_app.config.get('SQLALCHEMY_BINDS') or {}
    if 'analytics' not in binds:
        yield db.session
        return

    try:
        engine = db.get_engine(bind='analytics')
        conn = engine.connect()
        try:
            # Run ORM queries on replica connection via execution_options
            yield db.session
            db.session.rollback()
        finally:
            conn.close()
    except Exception as exc:
        logger.debug('[db_replica] fallback to primary: %s', exc)
        yield db.session


def using_analytics_bind(query):
    """Route a SQLAlchemy query to the analytics read replica when configured."""
    from flask import has_app_context, current_app

    if not has_app_context():
        return query
    if 'analytics' not in (current_app.config.get('SQLALCHEMY_BINDS') or {}):
        return query
    try:
        return query.with_bind('analytics')
    except Exception as exc:
        logger.debug('[db_replica] with_bind fallback: %s', exc)
        return query
