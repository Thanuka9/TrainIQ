"""Tests for learner area progress summary."""
from unittest.mock import MagicMock, patch

from utils.level_access import _area_study_percent, get_area_progress_summary


class _Area:
    def __init__(self, area_id, name):
        self.id = area_id
        self.name = name


class _Exam:
    def __init__(self, exam_id=1):
        self.id = exam_id


class _LevelArea:
    def __init__(self, area_id, required_exam=None, area=None):
        self.area_id = area_id
        self.required_exam_id = required_exam.id if required_exam else None
        self.required_exam = required_exam
        self.area = area or _Area(area_id, f"Area {area_id}")


class _Level:
    def __init__(self, level_id=10, level_number=2):
        self.id = level_id
        self.level_number = level_number


class _User:
    def __init__(self, user_id=5, current_level=2):
        self.id = user_id
        self.current_level = current_level

    def get_current_level(self):
        return self.current_level

    def can_skip_exam(self, _exam):
        return False


def test_get_area_progress_summary_empty_without_user():
    assert get_area_progress_summary(None) == []


def test_get_area_progress_summary_builds_rows_for_current_level():
    user = _User()
    level = _Level()
    la = _LevelArea(3, required_exam=_Exam(), area=_Area(3, "Billing"))

    query = MagicMock()
    query.filter_by.return_value.first.return_value = level

    with patch("utils.level_access.LevelArea") as LevelAreaMock, patch(
        "utils.level_access._area_study_percent", return_value=75
    ), patch("utils.level_access.has_passed_exam", return_value=True), patch(
        "utils.tenant_utils.tenant_levels_query", return_value=query
    ):
        LevelAreaMock.query.filter_by.return_value.all.return_value = [la]
        summary = get_area_progress_summary(user)

    assert len(summary) == 1
    assert summary[0]["area_name"] == "Billing"
    assert summary[0]["study_percent"] == 75
    assert summary[0]["exam_required"] is True
    assert summary[0]["exam_passed"] is True


def test_area_study_percent_returns_100_when_no_materials():
    with patch("utils.level_access.db.session.query") as query:
        query.return_value.filter_by.return_value.all.side_effect = [
            [(1,)],  # category ids
            [],      # material ids
        ]
        assert _area_study_percent(1, 10, 3) == 100


def test_area_study_percent_averages_material_progress(app):
    progress = MagicMock()
    progress.study_material_id = 100
    progress.progress_percentage = 50
    progress.completed = False

    filter_mock = MagicMock()
    filter_mock.all.return_value = [progress]

    cat_query = MagicMock()
    cat_query.filter_by.return_value.all.return_value = [(1,)]
    mat_query = MagicMock()
    mat_query.filter.return_value.all.return_value = [(100,), (101,)]

    with app.app_context():
        with patch("utils.level_access.db.session.query", side_effect=[cat_query, mat_query]), patch(
            "utils.level_access.UserProgress.query"
        ) as progress_query:
            progress_query.filter.return_value = filter_mock
            assert _area_study_percent(1, 10, 3) == 25
