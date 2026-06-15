"""Tests for per-exam retry cooldown helpers."""
from datetime import timedelta

from utils.exam_retry import DEFAULT_RETRY_DAYS, retry_cooldown_days, retry_period


class _Exam:
    def __init__(self, retry_cooldown_days=None):
        self.retry_cooldown_days = retry_cooldown_days


def test_retry_cooldown_default():
    assert retry_cooldown_days(_Exam()) == DEFAULT_RETRY_DAYS
    assert retry_cooldown_days(_Exam(None)) == DEFAULT_RETRY_DAYS


def test_retry_cooldown_custom():
    assert retry_cooldown_days(_Exam(7)) == 7
    assert retry_cooldown_days(_Exam(0)) == 0


def test_retry_cooldown_invalid_falls_back():
    assert retry_cooldown_days(_Exam("bad")) == DEFAULT_RETRY_DAYS
    assert retry_cooldown_days(_Exam(-5)) == 0


def test_retry_period_timedelta():
    assert retry_period(_Exam(14)) == timedelta(days=14)


def test_special_exam_retry_period_default():
    from utils.exam_retry import special_exam_retry_period

    assert special_exam_retry_period(1, 1) == timedelta(days=DEFAULT_RETRY_DAYS)
    assert special_exam_retry_period(1, 2) == timedelta(days=DEFAULT_RETRY_DAYS)


def test_special_exam_retry_period_from_exam():
    from unittest.mock import MagicMock, patch
    from utils.exam_retry import special_exam_retry_period

    fake_exam = _Exam(14)
    with patch("models.Exam") as MockExam:
        MockExam.query.get.return_value = fake_exam
        assert special_exam_retry_period(1, 1) == timedelta(days=14)
        MockExam.query.get.assert_called_once()
