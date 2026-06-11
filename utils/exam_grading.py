"""Exam scoring helpers — passing thresholds, question types, letter grades."""
DEFAULT_PASSING_SCORE = 70.0


def get_passing_score(exam):
    return float(getattr(exam, "passing_score", None) or DEFAULT_PASSING_SCORE)


def passed(score, exam=None, threshold=None):
    t = threshold if threshold is not None else (get_passing_score(exam) if exam else DEFAULT_PASSING_SCORE)
    return float(score) >= float(t)


def calculate_grade(percentage, passing_score=None):
    passing_score = passing_score or DEFAULT_PASSING_SCORE
    p = float(percentage)
    ps = float(passing_score)
    if p >= ps + 20:
        return "A"
    if p >= ps + 10:
        return "B"
    if p >= ps:
        return "C"
    return "F"


def _normalize_set(value):
    if not value:
        return set()
    if isinstance(value, list):
        parts = value
    else:
        parts = str(value).replace("|", ",").split(",")
    return {p.strip().lower() for p in parts if p.strip()}


def score_single_choice(q, submitted):
    ans = submitted.strip(" \"'").lower()
    corr = q.correct_answer.strip(" \"'").lower()
    if ans == corr:
        return 100.0
    try:
        letter = getattr(q, "correct_ans", None)
        if letter and ans == str(letter).strip().lower():
            return 100.0
    except (ValueError, AttributeError):
        pass
    return 0.0


def score_multiple_choice(q, submitted_raw):
    user_set = _normalize_set(submitted_raw)
    correct_set = _normalize_set(q.correct_answer)
    if not correct_set:
        return 0.0
    if user_set == correct_set:
        return 100.0
    if user_set & correct_set:
        return round(100.0 * len(user_set & correct_set) / len(correct_set), 1)
    return 0.0


def score_structured(q, submitted_raw, exam=None):
    text = (submitted_raw or "").strip()
    if not text:
        return 0.0
    try:
        from utils.exam_rag import grade_structured_with_rag
        exam_obj = exam or getattr(q, "exam", None)
        return float(grade_structured_with_rag(q.question_text, q.correct_answer, text, exam=exam_obj))
    except Exception:
        from utils.local_ai import grade_structured_answer
        try:
            return float(grade_structured_answer(q.question_text, q.correct_answer, text))
        except Exception:
            return 0.0


def score_question(q, submitted_dict, exam=None):
    qtype = getattr(q, "question_type", None) or "single_choice"
    key = f"answers[{q.id}]"
    if qtype == "multiple_choice":
        raw = submitted_dict.getlist(key) if hasattr(submitted_dict, "getlist") else submitted_dict.get(key, "")
        return score_multiple_choice(q, raw)
    if qtype == "structured":
        raw = submitted_dict.get(key, "")
        return score_structured(q, raw, exam=exam)
    return score_single_choice(q, submitted_dict.get(key, ""))


def grade_exam(questions, submitted_dict, exam=None):
    if not questions:
        return 0.0
    per_q = 100.0 / len(questions)
    return round(
        sum(score_question(q, submitted_dict, exam=exam) * per_q / 100.0 for q in questions),
        2,
    )
