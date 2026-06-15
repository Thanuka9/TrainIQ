"""Tests for learner course recommendations."""
import pytest

from utils.learner_recommendations import get_recommended_next_course
from utils.level_access import material_progression_level


class _Designation:
    def __init__(self, starting_level):
        self.starting_level = starting_level

    def can_skip_level(self, target_level):
        return self.starting_level >= target_level


class _Level:
    def __init__(self, level_number):
        self.level_number = level_number


class _User:
    def __init__(self, user_id=1, current_level=2, designation=None, tenant_id=1):
        self.id = user_id
        self.current_level = current_level
        self.designation = designation
        self.tenant_id = tenant_id

    def get_current_level(self):
        return self.current_level or 1


class _Material:
    def __init__(self, material_id, minimum_level=1, level=None, tenant_id=1):
        self.id = material_id
        self.minimum_level = minimum_level
        self.level = level
        self.level_id = level.level_number if level else None
        self.tenant_id = tenant_id
        self.title = f"Course {material_id}"


@pytest.fixture
def app_ctx(app):
    with app.app_context():
        yield


def test_get_recommended_next_course_picks_first_incomplete_at_level(app_ctx, monkeypatch):
    user = _User(current_level=2, designation=_Designation(1))
    materials = [
        _Material(1, level=_Level(2)),
        _Material(2, level=_Level(2)),
        _Material(3, level=_Level(3)),
    ]
    completed_ids = {1}

    class _Query:
        def order_by(self, *_args):
            return self

        def all(self):
            return materials

    monkeypatch.setattr(
        "utils.learner_recommendations.filter_by_user_tenant",
        lambda q, _model: _Query(),
    )
    monkeypatch.setattr(
        "utils.learner_recommendations._material_complete",
        lambda _uid, mid: mid in completed_ids,
    )

    rec = get_recommended_next_course(user)
    assert rec is not None
    assert rec.id == 2
    assert material_progression_level(rec) == 2


def test_get_recommended_next_course_returns_none_when_all_complete(app_ctx, monkeypatch):
    user = _User(current_level=1, designation=_Designation(1))
    materials = [_Material(10, level=_Level(1))]

    class _Query:
        def order_by(self, *_args):
            return self

        def all(self):
            return materials

    monkeypatch.setattr(
        "utils.learner_recommendations.filter_by_user_tenant",
        lambda q, _model: _Query(),
    )
    monkeypatch.setattr(
        "utils.learner_recommendations._material_complete",
        lambda _uid, _mid: True,
    )

    assert get_recommended_next_course(user) is None


def test_get_recommended_next_course_skips_inaccessible(app_ctx, monkeypatch):
    user = _User(current_level=1, designation=_Designation(1))
    materials = [
        _Material(1, level=_Level(3)),
        _Material(2, level=_Level(1)),
    ]

    class _Query:
        def order_by(self, *_args):
            return self

        def all(self):
            return materials

    monkeypatch.setattr(
        "utils.learner_recommendations.filter_by_user_tenant",
        lambda q, _model: _Query(),
    )
    monkeypatch.setattr(
        "utils.learner_recommendations._material_complete",
        lambda _uid, _mid: False,
    )

    rec = get_recommended_next_course(user)
    assert rec is not None
    assert rec.id == 2
