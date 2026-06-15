"""Tests for study/exam completion helpers."""


class _Progress:
    def __init__(self, material_id, completed=False, progress_percentage=0):
        self.study_material_id = material_id
        self.completed = completed
        self.progress_percentage = progress_percentage


class _FakeQuery:
    def __init__(self, rows):
        self._rows = rows

    def filter(self, *args, **kwargs):
        return self

    def filter_by(self, **kwargs):
        return self

    def all(self):
        return self._rows

    def distinct(self):
        return self

    def count(self):
        return len(self._rows)


class _FakeSession:
    def __init__(self, level_area_rows, material_rows, progress_rows):
        self.level_area_rows = level_area_rows
        self.material_rows = material_rows
        self.progress_rows = progress_rows
        self._query_target = None

    def query(self, *entities):
        entity = entities[0]
        name = getattr(entity, "__name__", str(entity))

        class _Builder:
            def __init__(inner_self, outer, entity_name):
                inner_self.outer = outer
                inner_self.entity_name = entity_name
                inner_self.filters = {}

            def filter(inner_self, *args):
                return inner_self

            def filter_by(inner_self, **kwargs):
                inner_self.filters.update(kwargs)
                return inner_self

            def all(inner_self):
                if inner_self.entity_name == "LevelArea":
                    return inner_self.outer.level_area_rows
                if inner_self.entity_name == "StudyMaterial":
                    return inner_self.outer.material_rows
                return []

            def distinct(inner_self):
                return inner_self

            def count(inner_self):
                if inner_self.entity_name == "UserProgress":
                    return len(inner_self.outer.progress_rows)
                return 0

        return _Builder(self, name)


def test_has_finished_study_requires_all_materials_completed(monkeypatch):
    from utils import progress_utils

    calls = {"completed_count": 0, "material_count": 0}

    def fake_query(*entities):
        label = str(entities[0])

        class _Q:
            def filter_by(self, **_kwargs):
                return self

            def filter(self, *_args, **_kwargs):
                return self

            def all(self):
                if "LevelArea" in label:
                    return [(10,)]
                if "StudyMaterial" in label:
                    calls["material_count"] = 2
                    return [(101,), (102,)]
                return []

            def distinct(self):
                return self

            def count(self):
                return calls["completed_count"]

        return _Q()

    monkeypatch.setattr(
        progress_utils.db.session,
        "query",
        fake_query,
    )

    calls["completed_count"] = 1
    assert progress_utils.has_finished_study(user_id=1, level_id=5, area_id=2) is False

    calls["completed_count"] = 2
    assert progress_utils.has_finished_study(user_id=1, level_id=5, area_id=2) is True


def test_has_finished_study_true_when_no_materials_required(monkeypatch):
    from utils import progress_utils

    session = _FakeSession(
        level_area_rows=[],
        material_rows=[],
        progress_rows=[],
    )
    monkeypatch.setattr(progress_utils, "db", type("DB", (), {"session": session})())

    assert progress_utils.has_finished_study(user_id=1, level_id=5, area_id=2) is True
