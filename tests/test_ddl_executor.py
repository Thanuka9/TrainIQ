"""Tests for PostgreSQL DDL executor (CONCURRENTLY)."""
from utils.ddl_executor import prepare_postgres_ddl


def test_prepare_adds_concurrently_for_create_index():
    ddl = 'CREATE INDEX IF NOT EXISTS ix_users_join_date ON users (join_date)'
    sql, autocommit = prepare_postgres_ddl(ddl, use_concurrent=True)
    assert 'CONCURRENTLY' in sql
    assert autocommit is True


def test_prepare_skips_concurrently_when_disabled():
    ddl = 'CREATE INDEX IF NOT EXISTS ix_users_join_date ON users (join_date)'
    sql, autocommit = prepare_postgres_ddl(ddl, use_concurrent=False)
    assert 'CONCURRENTLY' not in sql
    assert autocommit is False


def test_prepare_non_index_sql_unchanged():
    ddl = 'ANALYZE users'
    sql, autocommit = prepare_postgres_ddl(ddl, use_concurrent=True)
    assert sql == 'ANALYZE users'
    assert autocommit is False


def test_prepare_idempotent_when_already_concurrent():
    ddl = 'CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_foo ON users (id)'
    sql, autocommit = prepare_postgres_ddl(ddl, use_concurrent=True)
    assert sql.count('CONCURRENTLY') == 1
    assert autocommit is True
