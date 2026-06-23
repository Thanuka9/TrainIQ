"""Shared thresholds for platform operations modules (override via env)."""
from __future__ import annotations

import os


def _int(name: str, default: int) -> int:
    try:
        return max(0, int(os.getenv(name, str(default))))
    except (TypeError, ValueError):
        return default


def _float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


# PostgreSQL
PG_SEQ_SCAN_RATIO_WARN = _float('OPS_PG_SEQ_SCAN_RATIO_WARN', 0.85)
PG_MIN_ROWS_FOR_SEQ_WARN = _int('OPS_PG_MIN_ROWS_FOR_SEQ_WARN', 1000)
PG_SLOW_QUERY_MS = _int('OPS_PG_SLOW_QUERY_MS', 750)
PG_CACHE_HIT_RATIO_WARN = _float('OPS_PG_CACHE_HIT_RATIO_WARN', 0.95)
PG_DEAD_TUPLES_WARN = _int('OPS_PG_DEAD_TUPLES_WARN', 50_000)

# MongoDB
MONGO_PROVISION_WORKERS = _int('OPS_MONGO_PROVISION_WORKERS', 8)
MONGO_STORAGE_WARN_MB = _int('OPS_MONGO_STORAGE_WARN_MB', 4096)

# AI / LearnIQ
AI_CACHE_MAX_MB = _int('OPS_AI_CACHE_MAX_MB', 512)
AI_LATENCY_WARN_MS = _int('OPS_AI_LATENCY_WARN_MS', 8000)
AI_BENCHMARK_ENABLED = os.getenv('OPS_AI_BENCHMARK_ENABLED', 'true').lower() in ('1', 'true', 'yes')
