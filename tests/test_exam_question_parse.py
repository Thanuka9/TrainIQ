"""Tests for AI exam question JSON parsing."""
from utils.local_ai import parse_json_response, _coerce_exam_questions


def test_parse_wrapped_json():
    raw = (
        'Here are questions:\n```json\n'
        '{"questions":[{"question_text":"What is revenue cycle management?","question_type":"single_choice",'
        '"choices":["A","B","C","D"],"correct_answer":"B"}]}\n```'
    )
    data = parse_json_response(raw)
    questions = _coerce_exam_questions(data)
    assert len(questions) == 1
    assert questions[0]["question_text"] == "What is revenue cycle management?"
    assert questions[0]["correct_answer"] == "B"


def test_parse_alternate_field_names():
    raw = '[{"question":"What is medical coding?","type":"single_choice","options":["One","Two","Three","Four"],"answer":"A"}]'
    questions = _coerce_exam_questions(parse_json_response(raw))
    assert len(questions) == 1
    assert questions[0]["question_text"] == "What is medical coding?"
    assert questions[0]["choices"][0] == "One"


def test_parse_trailing_commas():
    raw = '{"questions":[{"question_text":"Q3","question_type":"structured","choices":[],"correct_answer":"ans",}]}'
    questions = _coerce_exam_questions(parse_json_response(raw))
    assert len(questions) == 1
    assert questions[0]["question_type"] == "structured"


def test_validate_strips_choice_prefixes():
    from utils.exam_ai import validate_questions

    raw = [{
        "question_text": "Which step verifies patient insurance coverage before treatment?",
        "question_type": "single_choice",
        "choices": ["A) Intake", "B) Eligibility check", "C) Billing", "D) Collections"],
        "correct_answer": "B",
        "source_excerpt": (
            "Verification of benefits and eligibility check must occur before scheduled services. "
            "Intake collects demographics. Billing happens after the visit."
        ),
    }]
    out = validate_questions(raw, require_grounding=True)
    assert len(out) == 1
    assert out[0]["choices"][0] == "Intake"
    assert out[0]["correct_answer"] == "B"


def test_dedupe_similar_questions():
    from utils.exam_ai import dedupe_questions

    qs = [
        {"question_text": "What is HIPAA privacy rule?"},
        {"question_text": "What is the HIPAA privacy rule?"},
        {"question_text": "Define medical coding standards."},
    ]
    out = dedupe_questions(qs)
    assert len(out) == 2
