"""Tests for level unlock and course access helpers."""
from utils.level_access import (
    can_access_study_material,
    can_access_level_number,
    material_progression_level,
)


class _Designation:
    def __init__(self, starting_level, desig_id=1):
        self.id = desig_id
        self.starting_level = starting_level

    def can_skip_level(self, target_level):
        return self.starting_level >= target_level


class _Level:
    def __init__(self, level_number):
        self.level_number = level_number


class _User:
    def __init__(self, current_level=1, designation=None, tenant_id=1):
        self.current_level = current_level
        self.designation = designation
        self.tenant_id = tenant_id
        self.id = 1

    def get_current_level(self):
        return self.current_level if self.current_level else 1

    def can_skip_level(self, target_level):
        if not self.designation:
            return False
        return self.designation.can_skip_level(target_level)

    def can_skip_exam(self, _exam):
        return False


class _Material:
    def __init__(self, minimum_level=1, level=None, level_id=None):
        self.minimum_level = minimum_level
        self.level = level
        self.level_id = level_id


def test_material_progression_level_prefers_linked_level():
    material = _Material(minimum_level=1, level=_Level(3))
    assert material_progression_level(material) == 3


def test_trainee_can_access_level_one_material():
    user = _User(current_level=1, designation=_Designation(1))
    material = _Material(minimum_level=1, level=_Level(1))
    assert can_access_study_material(user, material) is True


def test_trainee_blocked_from_level_three_without_progression():
    user = _User(current_level=1, designation=_Designation(1))
    material = _Material(minimum_level=1, level=_Level(3))
    assert can_access_study_material(user, material) is False


def test_senior_designation_skips_progression_gate():
    user = _User(current_level=1, designation=_Designation(3))
    material = _Material(minimum_level=1, level=_Level(3))
    assert can_access_study_material(user, material) is True


def test_designation_gate_blocks_low_rank_from_restricted_material():
    user = _User(current_level=5, designation=_Designation(1))
    material = _Material(minimum_level=4, level=_Level(1))
    assert can_access_study_material(user, material) is False


def test_progression_unlocks_when_current_level_reaches_material():
    user = _User(current_level=3, designation=_Designation(1))
    material = _Material(minimum_level=1, level=_Level(3))
    assert can_access_study_material(user, material) is True


def test_can_access_level_number_allows_level_one():
    user = _User(current_level=1)
    assert can_access_level_number(user, 1) is True


def test_user_can_skip_level_matches_designation():
    user = _User(designation=_Designation(4))
    assert user.can_skip_level(3) is True
    assert user.can_skip_level(5) is False


def test_can_access_exam_level_allows_designation_skip():
    from utils.level_access import can_access_exam_level

    class _Exam:
        level = _Level(4)

    user = _User(current_level=1, designation=_Designation(5))
    assert can_access_exam_level(user, _Exam()) is True

    user = _User(current_level=1, designation=_Designation(1))
    assert can_access_exam_level(user, _Exam()) is False


def test_exam_is_skippable_compares_starting_levels():
    class _Exam:
        minimum_designation_level = 99

        def is_skippable(self, user):
            if not self.minimum_designation_level or not user.designation:
                return False
            required = _Designation(3, desig_id=99)
            return user.designation.starting_level >= required.starting_level

    exam = _Exam()
    user = _User(designation=_Designation(5, desig_id=10))
    assert exam.is_skippable(user) is True
    user.designation = _Designation(2, desig_id=10)
    assert exam.is_skippable(user) is False
