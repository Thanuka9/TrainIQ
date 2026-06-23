"""Collect PostgreSQL and MongoDB performance signals for the optimizer agent."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import inspect, text

from utils.ops_constants import (
    PG_CACHE_HIT_RATIO_WARN,
    PG_DEAD_TUPLES_WARN,
    PG_MIN_ROWS_FOR_SEQ_WARN,
    PG_SEQ_SCAN_RATIO_WARN,
    PG_SLOW_QUERY_MS,
)

logger = logging.getLogger(__name__)

MONITORED_TABLES = (
    'users',
    'tenants',
    'notifications',
    'user_scores',
    'audit_log',
    'support_tickets',
    'course_notes',
    'exams',
    'study_materials',
    'billing_events',
    'tenant_invites',
    'announcements',
    'tasks',
)


@dataclass
class MonitorIssue:
    severity: str
    category: str
    message: str
    detail: dict[str, Any] = field(default_factory=dict)


def _is_postgres(conn) -> bool:
    try:
        return conn.dialect.name == 'postgresql'
    except Exception:
        return False


def _existing_index_names(conn) -> set[str]:
    names: set[str] = set()
    insp = inspect(conn)
    for tbl in insp.get_table_names():
        for idx in insp.get_indexes(tbl):
            names.add(idx['name'])
    return names


def _collect_connection_stats(conn) -> dict[str, Any]:
    try:
        row = conn.execute(
            text(
                """
                SELECT
                    (SELECT count(*) FROM pg_stat_activity WHERE datname = current_database()) AS active,
                    (SELECT setting::int FROM pg_settings WHERE name = 'max_connections') AS max_connections
                """
            )
        ).mappings().first()
        return {
            'active': int(row['active'] or 0),
            'max': int(row['max_connections'] or 0),
        }
    except Exception as exc:
        return {'error': str(exc)}


def _collect_cache_hit_ratio(conn) -> float | None:
    try:
        row = conn.execute(
            text(
                """
                SELECT
                    sum(blks_hit)::float / NULLIF(sum(blks_hit) + sum(blks_read), 0) AS ratio
                FROM pg_stat_database
                WHERE datname = current_database()
                """
            )
        ).scalar()
        return round(float(row), 4) if row is not None else None
    except Exception:
        return None


def _collect_database_size(conn) -> int:
    try:
        val = conn.execute(
            text("SELECT pg_database_size(current_database())")
        ).scalar()
        return int(val or 0)
    except Exception:
        return 0


def _collect_dead_tuples(conn) -> list[dict[str, Any]]:
    try:
        rows = conn.execute(
            text(
                """
                SELECT relname AS table_name,
                       n_live_tup AS live,
                       n_dead_tup AS dead,
                       last_vacuum,
                       last_autovacuum,
                       last_analyze,
                       last_autoanalyze
                FROM pg_stat_user_tables
                WHERE schemaname = 'public'
                  AND n_dead_tup >= :threshold
                ORDER BY n_dead_tup DESC
                LIMIT 15
                """
            ),
            {'threshold': max(1000, PG_DEAD_TUPLES_WARN // 10)},
        ).mappings().all()
        return [dict(r) for r in rows]
    except Exception:
        return []


def _collect_unused_indexes(conn) -> list[dict[str, Any]]:
    try:
        rows = conn.execute(
            text(
                """
                SELECT s.relname AS table_name,
                       s.indexrelname AS index_name,
                       s.idx_scan,
                       pg_relation_size(s.indexrelid) AS index_bytes
                FROM pg_stat_user_indexes s
                JOIN pg_index i ON i.indexrelid = s.indexrelid
                WHERE s.schemaname = 'public'
                  AND NOT i.indisprimary
                  AND s.idx_scan = 0
                  AND pg_relation_size(s.indexrelid) > 65536
                ORDER BY pg_relation_size(s.indexrelid) DESC
                LIMIT 20
                """
            )
        ).mappings().all()
        return [dict(r) for r in rows]
    except Exception:
        return []


def _collect_slow_queries(conn) -> list[dict[str, Any]]:
    try:
        ext = conn.execute(
            text("SELECT 1 FROM pg_extension WHERE extname = 'pg_stat_statements'")
        ).fetchone()
        if not ext:
            return []

        rows = conn.execute(
            text(
                """
                SELECT LEFT(query, 200) AS query,
                       calls,
                       round(mean_exec_time::numeric, 2) AS mean_ms,
                       round(total_exec_time::numeric, 2) AS total_ms,
                       rows
                FROM pg_stat_statements
                WHERE query NOT ILIKE '%pg_stat_statements%'
                  AND mean_exec_time >= :min_ms
                ORDER BY mean_exec_time DESC
                LIMIT 10
                """
            ),
            {'min_ms': PG_SLOW_QUERY_MS},
        ).mappings().all()
        return [dict(r) for r in rows]
    except Exception as exc:
        logger.debug('slow query collection skipped: %s', exc)
        return []


def collect_postgres_stats() -> dict[str, Any]:
    """Return table scan stats, sizes, capacity metrics, and index inventory."""
    from extensions import db

    conn = db.engine.connect()
    try:
        if not _is_postgres(conn):
            return {'available': False, 'reason': 'not_postgresql'}

        stats: dict[str, Any] = {
            'available': True,
            'tables': [],
            'issues': [],
            'index_names': sorted(_existing_index_names(conn)),
            'extensions': {},
            'capacity': {},
        }

        cache_ratio = _collect_cache_hit_ratio(conn)
        connections = _collect_connection_stats(conn)
        db_size = _collect_database_size(conn)
        dead_tuples = _collect_dead_tuples(conn)
        unused_indexes = _collect_unused_indexes(conn)
        slow_queries = _collect_slow_queries(conn)

        stats['capacity'] = {
            'cache_hit_ratio': cache_ratio,
            'connections': connections,
            'database_size_bytes': db_size,
            'database_size_mb': round(db_size / (1024 * 1024), 2),
            'dead_tuple_tables': dead_tuples,
            'unused_indexes': unused_indexes,
            'slow_queries': slow_queries,
        }

        if cache_ratio is not None and cache_ratio < PG_CACHE_HIT_RATIO_WARN:
            stats['issues'].append({
                'severity': 'warning',
                'category': 'cache_hit',
                'message': (
                    f'Buffer cache hit ratio is {cache_ratio:.1%} '
                    f'(target ≥ {PG_CACHE_HIT_RATIO_WARN:.0%}). Consider more RAM or query tuning.'
                ),
            })

        max_conn = connections.get('max') or 0
        active = connections.get('active') or 0
        if max_conn and active / max_conn > 0.85:
            stats['issues'].append({
                'severity': 'warning',
                'category': 'connections',
                'message': (
                    f'PostgreSQL connections at {active}/{max_conn} '
                    f'({100 * active / max_conn:.0f}% of max).'
                ),
            })

        for row in dead_tuples:
            dead = int(row.get('dead') or 0)
            if dead >= PG_DEAD_TUPLES_WARN:
                stats['issues'].append({
                    'severity': 'warning',
                    'category': 'dead_tuples',
                    'table': row.get('table_name'),
                    'message': (
                        f"Table '{row.get('table_name')}' has {dead:,} dead tuples — "
                        'run maintenance ANALYZE; consider VACUUM during low traffic.'
                    ),
                })

        for row in unused_indexes:
            stats['issues'].append({
                'severity': 'info',
                'category': 'unused_index',
                'table': row.get('table_name'),
                'message': (
                    f"Index '{row.get('index_name')}' on '{row.get('table_name')}' "
                    f"has 0 scans ({int(row.get('index_bytes') or 0) // 1024} KB)."
                ),
            })

        for row in slow_queries:
            stats['issues'].append({
                'severity': 'warning',
                'category': 'slow_query',
                'message': (
                    f"Slow query (mean {row.get('mean_ms')} ms, {row.get('calls')} calls): "
                    f"{row.get('query', '')[:120]}"
                ),
            })

        table_rows = conn.execute(
            text(
                """
                SELECT relname AS table_name,
                       n_live_tup AS row_estimate,
                       seq_scan,
                       idx_scan,
                       pg_total_relation_size(relid) AS total_bytes
                FROM pg_stat_user_tables
                WHERE schemaname = 'public'
                ORDER BY pg_total_relation_size(relid) DESC
                """
            )
        ).mappings().all()

        for row in table_rows:
            name = row['table_name']
            if name not in MONITORED_TABLES and not name.startswith('tenant'):
                continue
            seq_scan = int(row['seq_scan'] or 0)
            idx_scan = int(row['idx_scan'] or 0)
            rows_est = int(row['row_estimate'] or 0)
            total_scans = seq_scan + idx_scan
            seq_ratio = seq_scan / total_scans if total_scans else 0.0

            entry = {
                'table': name,
                'rows': rows_est,
                'seq_scan': seq_scan,
                'idx_scan': idx_scan,
                'seq_scan_ratio': round(seq_ratio, 3),
                'total_bytes': int(row['total_bytes'] or 0),
            }
            stats['tables'].append(entry)

            if (
                rows_est >= PG_MIN_ROWS_FOR_SEQ_WARN
                and total_scans >= 100
                and seq_ratio >= PG_SEQ_SCAN_RATIO_WARN
            ):
                stats['issues'].append({
                    'severity': 'warning',
                    'category': 'seq_scan',
                    'table': name,
                    'message': (
                        f"Table '{name}' has high sequential scan ratio "
                        f"({seq_ratio:.0%}, {seq_scan} seq / {idx_scan} idx)."
                    ),
                })

            if rows_est >= PG_MIN_ROWS_FOR_SEQ_WARN and idx_scan == 0 and seq_scan > 50:
                stats['issues'].append({
                    'severity': 'warning',
                    'category': 'large_table_no_index_use',
                    'table': name,
                    'message': (
                        f"Large table '{name}' (~{rows_est:,} rows) "
                        'shows no index usage in pg_stat_user_tables.'
                    ),
                })

        ext_row = conn.execute(
            text(
                """
                SELECT extname
                FROM pg_extension
                WHERE extname IN ('pg_trgm', 'pg_stat_statements')
                """
            )
        ).fetchall()
        stats['extensions'] = {name: True for (name,) in ext_row}

        if not stats['extensions'].get('pg_stat_statements'):
            stats['issues'].append({
                'severity': 'info',
                'category': 'extension',
                'message': (
                    'pg_stat_statements is not enabled — slow-query detection is limited '
                    'to sequential scan heuristics. Enable via CREATE EXTENSION pg_stat_statements.'
                ),
            })

        return stats
    except Exception as exc:
        logger.warning('Postgres performance collection failed: %s', exc)
        return {'available': False, 'reason': str(exc)}
    finally:
        conn.close()


def collect_mongo_stats() -> dict[str, Any]:
    """Return MongoDB monitor snapshot (delegates to mongo_platform)."""
    try:
        from utils.mongo_platform import collect_mongo_monitor_stats

        return collect_mongo_monitor_stats()
    except Exception as exc:
        logger.warning('MongoDB performance collection failed: %s', exc)
        return {'available': False, 'reason': str(exc)}


def build_monitor_report() -> dict[str, Any]:
    """Run all collectors and return a unified report dict."""
    postgres = collect_postgres_stats()
    mongo = collect_mongo_stats()
    issues: list[dict[str, Any]] = []
    issues.extend(postgres.get('issues') or [])
    issues.extend(mongo.get('issues') or [])

    warning_count = sum(1 for i in issues if i.get('severity') == 'warning')
    critical_count = sum(1 for i in issues if i.get('severity') == 'critical')
    if critical_count:
        status = 'critical'
    elif warning_count:
        status = 'warning'
    elif not postgres.get('available'):
        status = 'degraded'
    else:
        status = 'healthy'

    return {
        'status': status,
        'issue_count': len(issues),
        'warning_count': warning_count,
        'critical_count': critical_count,
        'issues': issues,
        'postgres': postgres,
        'mongo': mongo,
        'search_engine': {
            'elasticsearch_recommended': False,
            'reason': (
                'TrainIQ uses tenant-scoped SQL search at current scale. '
                'Prefer PostgreSQL indexes/pg_trgm before adding Elasticsearch.'
            ),
        },
    }


def save_snapshot(report: dict[str, Any]):
    """Persist a monitor report as a DbPerformanceSnapshot row."""
    from extensions import db
    from models import DbPerformanceSnapshot

    summary = {
        'status': report['status'],
        'issue_count': report['issue_count'],
        'warning_count': report.get('warning_count', 0),
        'issues': report.get('issues', [])[:50],
        'search_engine': report.get('search_engine'),
        'postgres_capacity': (report.get('postgres') or {}).get('capacity'),
        'mongo_server': (report.get('mongo') or {}).get('server'),
    }
    snap = DbPerformanceSnapshot(
        status=report['status'],
        issue_count=report['issue_count'],
        recommendation_count=0,
        summary_json=json.dumps(summary),
        postgres_stats_json=json.dumps(report.get('postgres') or {}),
        mongo_stats_json=json.dumps(report.get('mongo') or {}),
    )
    db.session.add(snap)
    db.session.flush()
    try:
        from utils.db_metric_samples import record_metric_samples

        record_metric_samples(snap.id, report)
    except Exception as exc:
        logger.debug('metric sample persist skipped: %s', exc)
    return snap
