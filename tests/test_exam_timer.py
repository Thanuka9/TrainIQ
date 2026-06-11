"""Tests for exam timer context helper."""
from datetime import datetime, timezone

from utils.exam_timer import exam_timer_context, parse_exam_start


def test_parse_utc_offset_start_time():
    dt = parse_exam_start("2026-06-10T12:00:00+00:00")
    assert dt.tzinfo is not None
    assert dt.year == 2026


def test_parse_naive_start_time():
    dt = parse_exam_start("2026-06-10T12:00:00")
    assert dt.tzinfo is not None


def test_exam_timer_context():
    ctx = exam_timer_context("2026-06-10T12:00:00+00:00", 45)
    assert ctx["duration_minutes"] == 45
    assert ctx["duration_seconds"] == 45 * 60
    assert ctx["start_time_epoch_ms"] > 0
