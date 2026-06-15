"""Tests for course progress recalculation."""
from utils.course_progress import recalc_user_progress


class _Material:
    total_pages = 10


class _Prog:
    def __init__(self):
        self.pages_visited = 0
        self.asset_progress = {}
        self.progress_percentage = 0
        self.completed = False
        self.completion_date = None


class _AssetMaterial:
    id = 1
    total_pages = 3
    files = []
    media_assets = [
        {"id": "a1", "type": "pdf", "title": "A"},
        {"id": "a2", "type": "video", "title": "B"},
    ]


def test_recalc_from_asset_progress_average():
    m = _AssetMaterial()
    p = _Prog()
    p.asset_progress = {"a1": 100, "a2": 50}
    recalc_user_progress(m, p)
    assert p.progress_percentage == 75
    assert p.completed is False


def test_recalc_marks_complete_at_100():
    m = _AssetMaterial()
    p = _Prog()
    p.asset_progress = {"a1": 100, "a2": 100}
    recalc_user_progress(m, p)
    assert p.progress_percentage == 100
    assert p.completed is True
