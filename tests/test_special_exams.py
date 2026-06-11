from utils.special_exams import special_paper_ids, special_paper_id, is_special_exam_id, special_paper_label


def test_default_tenant_paper_ids():
    p1, p2 = special_paper_ids(1)
    assert p1 == 9991
    assert p2 == 9992


def test_other_tenant_paper_ids():
    p1, p2 = special_paper_ids(2)
    assert p1 == 10191
    assert p2 == 10192


def test_special_paper_id_helper():
    assert special_paper_id(1, 1) == 9991
    assert special_paper_id(1, 2) == 9992


def test_is_special_exam_id():
    assert is_special_exam_id(9991)
    assert is_special_exam_id(10192)
    assert not is_special_exam_id(42)


def test_special_paper_label():
    assert special_paper_label(9991) == "Special Exam Paper 1"
    assert special_paper_label(10192) == "Special Exam Paper 2"
