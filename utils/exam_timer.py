"""Helpers for exam countdown timers in templates."""
from __future__ import annotations

from datetime import datetime, timezone


def parse_exam_start(start_time_str: str) -> datetime:
    """Parse ISO start time from session (naive UTC or offset-aware)."""
    if not start_time_str:
        return datetime.now(timezone.utc)
    raw = start_time_str.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    dt = datetime.fromisoformat(raw)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def exam_timer_context(start_time_str: str, duration_minutes: int) -> dict:
    """Template context for reliable JS countdown."""
    duration = max(int(duration_minutes or 60), 1)
    started = parse_exam_start(start_time_str)
    return {
        "start_time": start_time_str,
        "start_time_epoch_ms": int(started.timestamp() * 1000),
        "duration_minutes": duration,
        "duration_seconds": duration * 60,
    }
