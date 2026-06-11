"""Shared helpers for RAG exam question generation and persistence."""
from __future__ import annotations

import logging
import re
from difflib import SequenceMatcher

logger = logging.getLogger(__name__)

_CHOICE_PREFIX = re.compile(r"^[A-Da-d][\.\)\]:\-]\s*")
_GENERIC_CHOICE = re.compile(r"^option\s*[a-d1-4]$", re.I)
_FILLER_PATTERNS = (
    re.compile(r"^all of the above$", re.I),
    re.compile(r"^none of the above$", re.I),
)
_MIN_GROUNDING = 0.06


def _normalize_qtext(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def _strip_choice_prefix(choice: str) -> str:
    return _CHOICE_PREFIX.sub("", (choice or "").strip())


def _normalize_letter_answer(raw: str) -> str:
    letters = re.findall(r"[A-Da-d]", raw or "")
    return ",".join(l.upper() for l in letters)


def _choices_are_valid(choices: list[str]) -> bool:
    cleaned = [_strip_choice_prefix(c) for c in choices if str(c).strip()]
    if len(cleaned) < 4:
        return False
    if len(set(_normalize_qtext(c) for c in cleaned)) < len(cleaned):
        return False
    for c in cleaned:
        if _GENERIC_CHOICE.match(c.strip()):
            return False
        if len(c.strip()) < 3:
            return False
    filler = sum(1 for c in cleaned if any(p.match(c.strip()) for p in _FILLER_PATTERNS))
    if filler >= len(cleaned) - 1:
        return False
    return True


def _question_reads_well(qtext: str) -> bool:
    q = qtext.strip()
    if len(q) < 20:
        return False
    if not q.endswith("?"):
        return False
    return True


def _resolve_category(raw: str, category_options: list[str] | None) -> str:
    raw = (raw or "").strip()
    if not raw:
        return ""
    if not category_options:
        return raw
    raw_l = raw.lower()
    for opt in category_options:
        if opt.lower() == raw_l:
            return opt
    for opt in category_options:
        if raw_l in opt.lower() or opt.lower() in raw_l:
            return opt
    return ""


def validate_questions(
    questions,
    allowed_types=None,
    category_options=None,
    require_grounding=False,
):
    """Filter and fix AI-generated questions before save."""
    from utils.exam_rag import question_grounding_score

    allowed = set(allowed_types or ["single_choice", "multiple_choice", "structured"])
    out = []

    for q in questions or []:
        if not isinstance(q, dict):
            continue

        qtext = (q.get("question_text") or "").strip()
        if not _question_reads_well(qtext):
            continue

        qtype = (q.get("question_type") or "single_choice").strip()
        if qtype not in allowed:
            qtype = "single_choice"

        choices = q.get("choices") or []
        if isinstance(choices, str):
            choices = [c.strip() for c in choices.split(",") if c.strip()]
        choices = [_strip_choice_prefix(str(c)) for c in choices if str(c).strip()][:4]

        raw_ans = str(q.get("correct_answer") or "").strip()
        category = _resolve_category(q.get("category"), category_options)
        excerpt = q.get("source_excerpt") or ""

        if require_grounding and excerpt:
            score = question_grounding_score(qtext, choices, raw_ans, excerpt)
            if score < _MIN_GROUNDING:
                logger.debug("Rejected low-grounding question (%.2f): %s", score, qtext[:60])
                continue

        if qtype == "structured":
            if len(raw_ans) < 8:
                continue
            out.append(
                {
                    "question_text": qtext,
                    "question_type": "structured",
                    "choices": [],
                    "correct_answer": raw_ans,
                    "category": category,
                }
            )
            continue

        if not _choices_are_valid(choices):
            continue

        if qtype == "multiple_choice":
            letters = _normalize_letter_answer(raw_ans)
            if not letters:
                continue
            out.append(
                {
                    "question_text": qtext,
                    "question_type": "multiple_choice",
                    "choices": choices,
                    "correct_answer": letters,
                    "category": category,
                }
            )
            continue

        letter = _normalize_letter_answer(raw_ans)
        if len(letter) == 1 and "A" <= letter <= "D":
            pass
        elif raw_ans and choices:
            matched = False
            for i, c in enumerate(choices):
                if _normalize_qtext(c) == _normalize_qtext(raw_ans):
                    letter = chr(ord("A") + i)
                    matched = True
                    break
            if not matched:
                continue
        else:
            continue

        out.append(
            {
                "question_text": qtext,
                "question_type": "single_choice",
                "choices": choices[:4],
                "correct_answer": letter[:1],
                "category": category,
            }
        )

    return out


def dedupe_questions(questions, similarity_threshold=0.78):
    kept = []
    norms = []
    for q in questions or []:
        norm = _normalize_qtext(q.get("question_text", ""))
        if not norm:
            continue
        if any(SequenceMatcher(None, norm, prev).ratio() >= similarity_threshold for prev in norms):
            continue
        kept.append(q)
        norms.append(norm)
    return kept


def persist_generated_questions(exam, questions_list, *, replace_existing=False):
    from models import Question, db, Category
    from utils.tenant_utils import user_tenant_id

    cleaned = validate_questions(questions_list)
    if replace_existing:
        Question.query.filter_by(exam_id=exam.id).delete()

    saved = 0
    for q_data in cleaned:
        qtype = (q_data.get("question_type") or "single_choice").strip()
        choices_list = q_data.get("choices") or []
        if isinstance(choices_list, str):
            choices_list = [c.strip() for c in choices_list.split(",") if c.strip()]
        choices_str = ",".join(choices_list[:4]) if qtype != "structured" else ""

        raw_ans = str(q_data.get("correct_answer", q_data.get("correct_ans", ""))).strip()
        qtext = (q_data.get("question_text") or "").strip()
        if not qtext:
            continue

        category_name = (q_data.get("category") or "").strip()
        category_id = exam.category_id
        if category_name:
            cat = Category.query.filter(
                Category.name.ilike(category_name),
                Category.tenant_id == (getattr(exam, 'tenant_id', None) or user_tenant_id()),
            ).first()
            if cat:
                category_id = cat.id

        if qtype == "structured":
            q = Question(
                exam_id=exam.id,
                question_text=qtext,
                choices="",
                correct_answer=raw_ans or "—",
                category_id=category_id,
                question_type="structured",
            )
        elif qtype == "multiple_choice":
            q = Question(
                exam_id=exam.id,
                question_text=qtext,
                choices=choices_str,
                correct_answer=raw_ans.upper().replace(" ", ""),
                category_id=category_id,
                question_type="multiple_choice",
            )
        else:
            letter = raw_ans.upper()[:1]
            ans_val = letter
            if len(letter) == 1 and "A" <= letter <= "D" and choices_list:
                idx = ord(letter) - ord("A")
                if 0 <= idx < len(choices_list):
                    ans_val = choices_list[idx]
            q = Question(
                exam_id=exam.id,
                question_text=qtext,
                choices=choices_str,
                correct_answer=ans_val or (choices_list[0] if choices_list else "A"),
                category_id=category_id,
                question_type="single_choice",
            )
        db.session.add(q)
        saved += 1

    db.session.commit()
    return saved


def validate_material_ids_for_tenant(material_ids, tenant_id):
    from models import StudyMaterial

    valid = []
    for mid in material_ids or []:
        try:
            mat = StudyMaterial.query.get(int(mid))
        except (TypeError, ValueError):
            continue
        if mat and mat.tenant_id == tenant_id:
            valid.append(mat.id)
    return valid
