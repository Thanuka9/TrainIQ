"""Per-exam retry cooldown helpers."""
from __future__ import annotations

from datetime import timedelta

DEFAULT_RETRY_DAYS = 30


def retry_cooldown_days(exam) -> int:
    raw = getattr(exam, "retry_cooldown_days", None)
    try:
        days = int(raw) if raw is not None else DEFAULT_RETRY_DAYS
    except (TypeError, ValueError):
        days = DEFAULT_RETRY_DAYS
    return max(0, days)


def retry_period(exam) -> timedelta:
    return timedelta(days=retry_cooldown_days(exam))


def special_exam_retry_period(tenant_id, paper_num=1) -> timedelta:
    """Retry period for special exam papers (virtual exam IDs).

    Uses ``Exam.retry_cooldown_days`` when an Exam row exists for the
    tenant-scoped special paper id; otherwise ``DEFAULT_RETRY_DAYS`` (30).
    """
    from utils.special_exams import special_paper_id

    exam_id = special_paper_id(tenant_id, paper_num)
    try:
        from models import Exam

        exam = Exam.query.get(exam_id)
        if exam is not None:
            return retry_period(exam)
    except Exception:
        pass
    return timedelta(days=DEFAULT_RETRY_DAYS)
