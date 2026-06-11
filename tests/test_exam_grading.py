from utils.exam_grading import DEFAULT_PASSING_SCORE, passed


def test_default_passing_score():
    assert DEFAULT_PASSING_SCORE == 70.0


def test_passed_threshold():
    assert passed(70.0, threshold=70.0) is True
    assert passed(69.9, threshold=70.0) is False
    assert passed(100.0, threshold=70.0) is True
