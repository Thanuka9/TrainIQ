"""Tests for completion certificate PDF generation."""
import pytest

from utils.certificates import generate_completion_certificate, user_has_completed_material


class _Tenant:
    name = "Acme Training"


class _User:
    def __init__(self, user_id=1):
        self.id = user_id
        self.first_name = "Jane"
        self.last_name = "Learner"
        self.employee_email = "jane@acme.com"
        self.tenant = _Tenant()


class _Material:
    def __init__(self, material_id=42):
        self.id = material_id
        self.title = "Safety Fundamentals"


class _Progress:
    def __init__(self, pct=100, completed=True):
        self.progress_percentage = pct
        self.completed = completed
        self.completion_date = None


@pytest.fixture
def app_ctx(app):
    with app.app_context():
        yield


def test_user_has_completed_material_false_without_progress(app_ctx, monkeypatch):
    user = _User()
    material = _Material()

    def _fake_filter_by(**kwargs):
        class _P:
            def first(self):
                return None

        return _P()

    monkeypatch.setattr(
        "utils.certificates.UserProgress.query",
        type("Q", (), {"filter_by": staticmethod(_fake_filter_by)})(),
    )
    assert user_has_completed_material(user, material) is False


def test_user_has_completed_material_true_at_100(app_ctx, monkeypatch):
    user = _User()
    material = _Material()

    def _fake_filter_by(**kwargs):
        class _P:
            def first(self):
                return _Progress(100)

        return _P()

    monkeypatch.setattr(
        "utils.certificates.UserProgress.query",
        type("Q", (), {"filter_by": staticmethod(_fake_filter_by)})(),
    )
    assert user_has_completed_material(user, material) is True


def test_generate_completion_certificate_returns_none_when_incomplete(app_ctx, monkeypatch):
    user = _User()
    material = _Material()
    monkeypatch.setattr(
        "utils.certificates.user_has_completed_material",
        lambda u, m: False,
    )
    assert generate_completion_certificate(user, material) is None


def test_generate_completion_certificate_returns_pdf_bytes(app_ctx, monkeypatch):
    user = _User()
    material = _Material()

    def _fake_filter_by(**kwargs):
        class _P:
            def first(self):
                return _Progress(100)

        return _P()

    monkeypatch.setattr(
        "utils.certificates.UserProgress.query",
        type("Q", (), {"filter_by": staticmethod(_fake_filter_by)})(),
    )

    pdf = generate_completion_certificate(user, material)
    assert pdf is not None
    assert pdf[:4] == b"%PDF"
