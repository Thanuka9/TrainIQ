"""
Document-grounded exam RAG — retrieval + context assembly for any subject area.
Uses study-material text from GridFS (no external vector DB required).
Optional LangChain can be added later; core retrieval is self-contained.
"""
from __future__ import annotations

import logging
import re
from difflib import SequenceMatcher

logger = logging.getLogger(__name__)


def lexical_similarity(a: str, b: str) -> float:
    a = (a or "").strip().lower()
    b = (b or "").strip().lower()
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def tokenize(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", (text or "").lower()) if len(w) > 2}


def keyword_overlap(user_answer: str, reference: str, context: str = "") -> float:
    user_t = tokenize(user_answer)
    if not user_t:
        return 0.0
    ref_t = tokenize(reference) | tokenize(context)
    if not ref_t:
        return 0.0
    return len(user_t & ref_t) / max(len(user_t), 1)


def question_grounding_score(question_text: str, choices, correct_answer, source_excerpt: str) -> float:
    """
    0–1 overlap of question/answer terms with the source excerpt.
    Used to reject hallucinated AI questions not supported by the document.
    """
    excerpt = (source_excerpt or "").strip()
    if not excerpt:
        return 1.0
    src = tokenize(excerpt)
    if not src:
        return 1.0
    parts = [question_text or ""]
    if isinstance(choices, list):
        parts.extend(str(c) for c in choices)
    elif choices:
        parts.append(str(choices))
    parts.append(str(correct_answer or ""))
    q_tokens = tokenize(" ".join(parts))
    if not q_tokens:
        return 0.0
    return len(q_tokens & src) / len(q_tokens)


def get_exam_study_context(exam, max_chars: int = 8000) -> str:
    if not exam:
        return ""
    try:
        from models import StudyMaterial
        from study_material_routes import _get_course_document_text

        material = StudyMaterial.query.get(getattr(exam, "course_id", None))
        if not material:
            return ""
        text = _get_course_document_text(material)
        if len(text) > max_chars:
            text = text[:max_chars] + "\n…[truncated]"
        return text.strip()
    except Exception as e:
        logger.warning("exam RAG context failed: %s", e)
        return ""


def retrieve_relevant_chunks(full_text: str, query: str, top_k: int = 3, chunk_size: int = 900) -> str:
    if not full_text.strip():
        return ""
    paragraphs = [p.strip() for p in re.split(r"\n{2,}", full_text) if p.strip()]
    if not paragraphs:
        paragraphs = [full_text[i : i + chunk_size] for i in range(0, len(full_text), chunk_size)]
    q_tokens = tokenize(query)
    scored = []
    for para in paragraphs:
        p_tokens = tokenize(para)
        if not p_tokens:
            continue
        overlap = len(q_tokens & p_tokens) / max(len(q_tokens), 1) if q_tokens else 0
        scored.append((overlap, para))
    scored.sort(key=lambda x: x[0], reverse=True)
    chunks = [p for _, p in scored[:top_k]]
    return "\n\n---\n\n".join(chunks)


def grade_structured_with_rag(question_text, reference_answer, user_answer, exam=None):
    user_answer = (user_answer or "").strip()
    if not user_answer:
        return 0.0

    lex = lexical_similarity(user_answer, reference_answer) * 100
    full_ctx = get_exam_study_context(exam)
    chunks = retrieve_relevant_chunks(full_ctx, f"{question_text} {reference_answer}", top_k=3)
    kw = keyword_overlap(user_answer, reference_answer, chunks) * 100

    ai_score = None
    try:
        from utils.local_ai import grade_structured_answer_rag
        ai_score = float(
            grade_structured_answer_rag(
                question_text, reference_answer, user_answer, context_snippets=chunks
            )
        )
    except Exception as e:
        logger.warning("AI structured grade failed, using lexical fallback: %s", e)

    if ai_score is not None:
        if chunks:
            return round(min(100.0, 0.55 * ai_score + 0.25 * lex + 0.20 * kw), 1)
        return round(min(100.0, 0.70 * ai_score + 0.30 * lex), 1)

    return round(min(100.0, max(lex, kw * 0.85)), 1)


def get_material_text(material, max_chars: int = 8000) -> str:
    if not material:
        return ""
    try:
        from study_material_routes import _get_course_document_text

        text = _get_course_document_text(material)
        if len(text) > max_chars:
            text = text[:max_chars] + "\n…[truncated]"
        return text.strip()
    except Exception as e:
        logger.warning("material text extraction failed id=%s: %s", getattr(material, "id", None), e)
        return ""


def _split_text_chunks(text: str, chunk_size: int = 700) -> list[str]:
    if not text.strip():
        return []
    paragraphs = [p.strip() for p in re.split(r"\n{2,}", text) if p.strip()]
    if paragraphs:
        return paragraphs
    return [text[i : i + chunk_size] for i in range(0, len(text), chunk_size)]


def _pick_diverse_chunks(chunks: list[str], n: int) -> list[str]:
    if not chunks or n <= 0:
        return []
    if len(chunks) <= n:
        return chunks
    step = len(chunks) / n
    return [chunks[int(i * step)] for i in range(n)]


def build_material_chunk_pool(material_ids, max_chunks_per_doc: int = 10) -> list[dict]:
    """RAG chunk pool — one entry per document section for rotated retrieval."""
    from models import StudyMaterial

    pool: list[dict] = []
    for mid in material_ids:
        material = StudyMaterial.query.get(int(mid))
        if not material:
            continue
        full = get_material_text(material, max_chars=24000)
        if not full:
            continue
        chunks = _split_text_chunks(full)
        picked = _pick_diverse_chunks(chunks, max_chunks_per_doc) or chunks[:max_chunks_per_doc]
        level_label = (
            f"Level {material.level.level_number}"
            if getattr(material, "level", None)
            else f"Level {material.minimum_level or 1}"
        )
        cat_label = material.category.name if getattr(material, "category", None) else "General"
        for chunk in picked:
            pool.append(
                {
                    "material_id": material.id,
                    "title": material.title or f"Document {material.id}",
                    "category": cat_label,
                    "level": level_label,
                    "text": chunk,
                }
            )
    return pool


def select_focus_chunks(chunk_pool: list[dict], batch_index: int) -> dict:
    """Pick the RAG focus chunk for a generation batch (round-robin across pool)."""
    if not chunk_pool:
        return {"title": "Study material", "category": "General", "text": ""}
    return chunk_pool[batch_index % len(chunk_pool)]


def build_smart_generation_context(material_ids, question_count: int = 5, max_chars_total: int = 12000) -> str:
    from models import StudyMaterial

    if not material_ids:
        return ""

    ids = [int(i) for i in material_ids if i]
    chunks_wanted = max(2, min(4, (question_count + len(ids) - 1) // len(ids)))
    per_doc_budget = max(1500, max_chars_total // max(len(ids), 1))
    sections = []

    for mid in ids:
        material = StudyMaterial.query.get(mid)
        if not material:
            continue
        full = get_material_text(material, max_chars=16000)
        if not full:
            continue
        chunks = _split_text_chunks(full)
        picked = _pick_diverse_chunks(chunks, chunks_wanted)
        body = "\n\n".join(picked)
        if len(body) > per_doc_budget:
            body = body[:per_doc_budget] + "\n…[truncated]"
        level_label = (
            f"Level {material.level.level_number}"
            if getattr(material, "level", None)
            else f"Level {material.minimum_level or 1}"
        )
        cat_label = material.category.name if getattr(material, "category", None) else "General"
        header = f"=== {material.title} | {level_label} | {cat_label} ==="
        sections.append(f"{header}\n{body}")

    combined = "\n\n---\n\n".join(sections)
    if len(combined) > max_chars_total:
        combined = combined[:max_chars_total] + "\n…[truncated]"
    return combined


def get_multi_material_context(material_ids, max_chars_total: int = 14000, max_chars_per: int = 5000) -> str:
    from models import StudyMaterial

    if not material_ids:
        return ""

    sections = []
    per_doc = max(2000, max_chars_total // max(len(material_ids), 1))
    per_doc = min(per_doc, max_chars_per)

    for mid in material_ids:
        material = StudyMaterial.query.get(int(mid))
        if not material:
            continue
        text = get_material_text(material, max_chars=per_doc)
        if not text:
            continue
        level_label = (
            f"Level {material.level.level_number}"
            if getattr(material, "level", None)
            else f"Level {material.minimum_level or 1}"
        )
        cat_label = material.category.name if getattr(material, "category", None) else "General"
        header = f"=== {material.title} | {level_label} | {cat_label} ==="
        sections.append(f"{header}\n{text}")

    combined = "\n\n---\n\n".join(sections)
    if len(combined) > max_chars_total:
        combined = combined[:max_chars_total] + "\n…[truncated]"
    return combined


def collect_generation_metadata(material_ids, exam=None, tenant_id=None) -> dict:
    """Domain-agnostic metadata derived from selected documents and exam — not hardcoded RCM."""
    from models import StudyMaterial, Category
    from utils.tenant_utils import filter_by_user_tenant

    ids = [int(i) for i in (material_ids or []) if i]
    titles: list[str] = []
    level_labels: set[str] = set()
    categories: set[str] = set()

    for mid in ids:
        m = StudyMaterial.query.get(mid)
        if not m:
            continue
        if m.title:
            titles.append(m.title)
        if m.level:
            level_labels.add(f"Level {m.level.level_number}")
        elif m.minimum_level:
            level_labels.add(f"Level {m.minimum_level}")
        if m.category and m.category.name:
            categories.add(m.category.name)

    if exam and getattr(exam, "category", None) and exam.category.name:
        categories.add(exam.category.name)

    category_options = sorted(categories)
    if tenant_id and not category_options:
        q = Category.query
        q = filter_by_user_tenant(q, Category)
        category_options = sorted({c.name for c in q.all() if c.name})

    base_title = (exam.title if exam else None) or (titles[0] if titles else "Exam")
    scope = base_title
    if len(titles) > 1:
        scope = f"{base_title} (documents: {', '.join(titles[:4])}{'…' if len(titles) > 4 else ''})"

    level_str = ", ".join(sorted(level_labels)) or "All levels"
    if category_options:
        level_str += f" · Topics: {', '.join(category_options)}"

    domain_hint = ""
    if titles:
        domain_hint = f"Documents: {', '.join(titles[:6])}."
    if category_options:
        domain_hint += f" Subject areas: {', '.join(category_options)}."

    return {
        "scope": scope,
        "level_str": level_str,
        "document_titles": titles,
        "category_options": category_options,
        "domain_hint": domain_hint.strip(),
    }


def generate_questions_from_material(exam, count: int = 5, question_types=None):
    material_ids = [exam.course_id] if exam and exam.course_id else []
    return generate_questions_from_sources(
        exam,
        material_ids=material_ids,
        count=count,
        question_types=question_types,
    )


def generate_questions_from_sources(
    exam,
    material_ids=None,
    count: int = 5,
    question_types=None,
    exam_title=None,
    tenant_id=None,
):
    """Generate exam questions from study documents using per-chunk RAG + Gemma (Ollama)."""
    from utils.local_ai import generate_exam_questions_rag

    ids = [int(i) for i in (material_ids or []) if i]
    if not ids and exam and exam.course_id:
        ids = [exam.course_id]
    if not ids:
        return {"error": "Select at least one study document."}

    chunk_pool = build_material_chunk_pool(ids)
    context = build_smart_generation_context(ids, question_count=count)
    if not context.strip() and not chunk_pool:
        return {"error": "No readable text found in the selected documents."}

    meta = collect_generation_metadata(ids, exam=exam, tenant_id=tenant_id)
    if exam_title:
        meta["scope"] = exam_title

    types = question_types or ["single_choice", "structured"]
    result = generate_exam_questions_rag(
        exam_title=meta["scope"],
        level=meta["level_str"],
        material_text=context,
        count=count,
        question_types=types,
        chunk_pool=chunk_pool,
        category_options=meta["category_options"],
        domain_hint=meta["domain_hint"],
        document_titles=meta["document_titles"],
    )
    result["source_material_ids"] = ids
    result["source_count"] = len(ids)
    return result
