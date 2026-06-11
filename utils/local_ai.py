"""
TrainIQ Local AI Engine — Ollama / Gemma 4 (no API keys required).

Requires Ollama running locally: https://ollama.com
  ollama pull gemma4:e4b
  ollama serve
"""
import json
import logging
import os
import re

import requests

OLLAMA_BASE = os.getenv("OLLAMA_BASE", "http://127.0.0.1:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "gemma4:e4b")
OLLAMA_TIMEOUT = int(os.getenv("OLLAMA_TIMEOUT", "180"))
VISION_TEXT_MIN_CHARS = int(os.getenv("AI_VISION_MIN_CHARS", "120"))

# Gemma 4 E4B supports 128K tokens; keep a practical char budget for speed.
DEFAULT_CONTEXT_CHARS = int(os.getenv("OLLAMA_CONTEXT_CHARS", "12000"))

_MODEL_CACHE = {"resolved": None, "installed": None}


def _bases():
    return [OLLAMA_BASE.rstrip("/"), "http://127.0.0.1:11434", "http://localhost:11434"]


def list_installed_models(refresh=False):
    """Return model names installed in local Ollama."""
    if _MODEL_CACHE["installed"] is not None and not refresh:
        return _MODEL_CACHE["installed"]

    for base in _bases():
        try:
            r = requests.get(f"{base}/api/tags", timeout=5)
            if r.status_code == 200:
                names = [m.get("name", "") for m in r.json().get("models", [])]
                _MODEL_CACHE["installed"] = names
                return names
        except requests.exceptions.RequestException:
            continue

    _MODEL_CACHE["installed"] = []
    return []


def resolve_model(preferred=None):
    """
    Pick the best available model.
    Priority: OLLAMA_MODEL env → preferred arg → installed gemma4* → any gemma* → first installed.
    """
    if _MODEL_CACHE["resolved"] and not preferred:
        return _MODEL_CACHE["resolved"]

    installed = list_installed_models()
    if not installed:
        return preferred or OLLAMA_MODEL

    candidates = []
    if preferred:
        candidates.append(preferred)
    if OLLAMA_MODEL:
        candidates.append(OLLAMA_MODEL)
    candidates.extend(["gemma4:e4b", "gemma4", "gemma4:latest"])

    for name in candidates:
        if name in installed:
            _MODEL_CACHE["resolved"] = name
            return name
        # Partial match: gemma4 → gemma4:e4b
        for inst in installed:
            if inst == name or inst.startswith(f"{name}:") or name.startswith(f"{inst}:"):
                _MODEL_CACHE["resolved"] = inst
                return inst

    gemma_models = [m for m in installed if "gemma" in m.lower()]
    if gemma_models:
        _MODEL_CACHE["resolved"] = gemma_models[0]
        return gemma_models[0]

    _MODEL_CACHE["resolved"] = installed[0]
    return installed[0]


def get_ai_status():
    """Full engine status for UI and health checks."""
    installed = list_installed_models(refresh=True)
    reachable = bool(installed) or any(_ping_base(b) for b in _bases())

    if not reachable:
        return {
            "available": False,
            "model_ready": False,
            "model": OLLAMA_MODEL,
            "resolved_model": None,
            "installed_models": [],
            "engine": "ollama",
            "message": "Ollama is not running. Start it from the Ollama app or run: ollama serve",
        }

    resolved = resolve_model()
    model_ready = resolved in installed

    return {
        "available": True,
        "model_ready": model_ready,
        "model": OLLAMA_MODEL,
        "resolved_model": resolved,
        "installed_models": installed,
        "engine": "ollama",
        "message": (
            f"Ready — using {resolved} (no API keys)"
            if model_ready
            else f"Ollama is running but '{OLLAMA_MODEL}' is not installed. Run: ollama pull {OLLAMA_MODEL}"
        ),
    }


def _ping_base(base):
    try:
        return requests.get(f"{base.rstrip('/')}/api/tags", timeout=3).status_code == 200
    except requests.exceptions.RequestException:
        return False


def is_available():
    status = get_ai_status()
    return status["available"] and status["model_ready"]


def _build_user_message(content, images=None):
    """Build a chat message, attaching vision images when provided."""
    if images:
        clean = [img.split(",", 1)[-1] if "," in img else img for img in images if img]
        if clean:
            return {"role": "user", "content": content, "images": clean}
    return {"role": "user", "content": content}


def needs_vision_fallback(document_text, page_images=None):
    """Use Gemma 4 vision when text extraction is weak but a slide image exists."""
    return bool(page_images) and len((document_text or "").strip()) < VISION_TEXT_MIN_CHARS


def query_chat(messages, model=None, temperature=0.3, timeout=None, think=False, json_mode=False):
    """
    Query Ollama /api/chat (preferred for Gemma 4).
    messages: [{"role": "system"|"user"|"assistant", "content": "..."}]
    """
    model = resolve_model(model)
    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
        "think": think,
        "options": {"temperature": temperature},
    }
    if json_mode:
        payload["format"] = "json"
    timeout = timeout or OLLAMA_TIMEOUT

    last_err = None
    for base in _bases():
        try:
            response = requests.post(
                f"{base.rstrip('/')}/api/chat",
                json=payload,
                timeout=timeout,
            )
            if response.status_code == 200:
                data = response.json()
                msg = data.get("message", {})
                return (msg.get("content") or "").strip()
            body = response.text[:300]
            logging.error("Ollama chat %s returned %s: %s", base, response.status_code, body)
            if response.status_code == 404 and "not found" in body.lower():
                raise ConnectionError(
                    f"Model '{model}' not found. Run: ollama pull {OLLAMA_MODEL}"
                )
            last_err = Exception(f"Ollama returned status {response.status_code}")
        except requests.exceptions.RequestException as e:
            last_err = e
            logging.warning("Ollama chat connection failed (%s): %s", base, e)

    raise ConnectionError(
        "Ollama is not running locally. Open the Ollama app or run: ollama serve"
    )


def stream_chat(messages, model=None, temperature=0.3, think=False):
    """Yield text chunks from Ollama streaming /api/chat."""
    model = resolve_model(model)
    payload = {
        "model": model,
        "messages": messages,
        "stream": True,
        "think": think,
        "options": {"temperature": temperature},
    }
    for base in _bases():
        try:
            with requests.post(
                f"{base.rstrip('/')}/api/chat",
                json=payload,
                stream=True,
                timeout=OLLAMA_TIMEOUT,
            ) as response:
                if response.status_code != 200:
                    continue
                for line in response.iter_lines(decode_unicode=True):
                    if not line:
                        continue
                    try:
                        chunk = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    content = chunk.get("message", {}).get("content", "")
                    if content:
                        yield content
                    if chunk.get("done"):
                        return
                return
        except requests.exceptions.RequestException as e:
            logging.warning("Ollama stream failed (%s): %s", base, e)
    raise ConnectionError("Ollama streaming unavailable. Open the Ollama app.")


def query_local_model(prompt, model=None, temperature=0.3, timeout=None, system=None, think=False, images=None, json_mode=False):
    """Single-shot helper — routes through the chat API."""
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append(_build_user_message(prompt, images))
    return query_chat(
        messages,
        model=model,
        temperature=temperature,
        timeout=timeout,
        think=think,
        json_mode=json_mode,
    )


def _strip_model_fences(text):
    """Remove markdown fences and common model preamble."""
    if not text:
        return ""
    clean = text.strip()
    if "```" in clean:
        for part in re.findall(r"```(?:json)?\s*([\s\S]*?)```", clean, flags=re.IGNORECASE):
            part = part.strip()
            if part:
                return part
        parts = clean.split("```")
        if len(parts) >= 2:
            clean = parts[1]
            if clean.lower().startswith("json"):
                clean = clean[4:]
    return clean.strip()


def _repair_json_text(raw):
    """Best-effort fixes for common invalid JSON from local LLMs."""
    s = raw.strip()
    s = re.sub(r",\s*([}\]])", r"\1", s)  # trailing commas
    s = s.replace("\u201c", '"').replace("\u201d", '"').replace("\u2018", "'").replace("\u2019", "'")
    return s


def _balanced_json_slice(text, opener, closer):
    """Return the first balanced JSON slice starting at opener."""
    start = text.find(opener)
    if start == -1:
        return None
    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
            continue
        if ch == opener:
            depth += 1
        elif ch == closer:
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None


def parse_json_response(text):
    """Extract and parse a JSON object or array from model output."""
    if not text:
        return None
    clean = _strip_model_fences(text)
    candidates = []
    slices = []
    for opener, closer in (("[", "]"), ("{", "}")):
        chunk = _balanced_json_slice(clean, opener, closer)
        if chunk:
            pos = clean.find(opener)
            slices.append((pos, chunk))
    slices.sort(key=lambda x: x[0])
    candidates.extend(chunk for _, chunk in slices)
    if not candidates:
        start_arr = clean.find("[")
        end_arr = clean.rfind("]")
        if start_arr != -1 and end_arr > start_arr:
            candidates.append(clean[start_arr : end_arr + 1])
        start_obj = clean.find("{")
        end_obj = clean.rfind("}")
        if start_obj != -1 and end_obj > start_obj:
            candidates.append(clean[start_obj : end_obj + 1])
        candidates.append(clean)

    seen = set()
    for candidate in candidates:
        candidate = candidate.strip()
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        for attempt in (candidate, _repair_json_text(candidate)):
            try:
                return json.loads(attempt)
            except json.JSONDecodeError:
                continue
    return None


def _coerce_exam_questions(data):
    """Normalize parsed LLM output into a list of question dicts."""
    items = None
    if isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        for key in ("questions", "items", "data", "exam_questions", "results", "output"):
            val = data.get(key)
            if isinstance(val, list):
                items = val
                break
        if items is None and (data.get("question_text") or data.get("question")):
            items = [data]

    if not items:
        return []

    out = []
    for item in items:
        if not isinstance(item, dict):
            continue
        qtext = (
            item.get("question_text")
            or item.get("question")
            or item.get("text")
            or item.get("prompt")
            or ""
        )
        qtext = str(qtext).strip()
        if not qtext:
            continue

        qtype = str(item.get("question_type") or item.get("type") or "single_choice").strip().lower()
        qtype = qtype.replace("-", "_").replace(" ", "_")
        if qtype in ("mcq", "single", "singlechoice", "single_choice"):
            qtype = "single_choice"
        elif qtype in ("multiple", "multiplechoice", "multiple_choice", "multi"):
            qtype = "multiple_choice"
        elif qtype not in ("single_choice", "multiple_choice", "structured"):
            qtype = "single_choice"

        choices = item.get("choices") or item.get("options") or item.get("answers") or []
        if isinstance(choices, str):
            choices = [c.strip() for c in re.split(r"[,|\n]", choices) if c.strip()]
        elif isinstance(choices, dict):
            choices = [str(v).strip() for v in choices.values() if str(v).strip()]
        choices = [str(c).strip() for c in choices if str(c).strip()][:4]

        raw_ans = item.get("correct_answer", item.get("answer", item.get("correct", "")))
        if raw_ans is None:
            raw_ans = ""
        if isinstance(raw_ans, list):
            raw_ans = ",".join(str(x) for x in raw_ans)
        raw_ans = str(raw_ans).strip()

        if qtype == "structured":
            choices = []
        elif not choices and qtype != "structured":
            continue

        out.append(
            {
                "question_text": qtext,
                "question_type": qtype,
                "choices": choices,
                "correct_answer": raw_ans or ("A" if choices else "—"),
                "category": str(item.get("category") or "").strip(),
                "source_excerpt": str(item.get("source_excerpt") or "").strip(),
            }
        )
    return out


def truncate_context(text, max_chars=None):
    """Trim document context to a practical size for local inference speed."""
    max_chars = max_chars or DEFAULT_CONTEXT_CHARS
    if not text:
        return ""
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n...[truncated for speed]"


def _normalize_flashcards(cards):
    if not isinstance(cards, list):
        return []
    out = []
    for item in cards:
        if not isinstance(item, dict):
            continue
        front = str(item.get("front", "")).strip()
        back = str(item.get("back", "")).strip()
        if front and back:
            out.append({"front": front, "back": back})
    return out[:10]


# ─── LearnIQ ────────────────────────────────────────────────────────────────

def _learniq_format_rules():
    return (
        "FORMAT RULES:\n"
        "- Write for a learner reading on screen — short sections, no walls of text.\n"
        "- Use ## for one main heading only, ### for subsections.\n"
        "- Use bullet lists for key points; **bold** only critical terms.\n"
        "- End with a line: Key takeaway: (one sentence).\n"
        "- Do not repeat the prompt or say 'Based on the material'."
    )


def _learniq_messages(course_title, document_text, task_prompt, page_images=None):
    use_vision = needs_vision_fallback(document_text, page_images)
    system = (
        "You are LearnIQ, an expert AI study tutor for TrainIQ workplace learning — any subject or industry. "
        "Be accurate, practical, and exam-focused. "
        + _learniq_format_rules()
    )
    if use_vision:
        system += " You are viewing a training slide image — read all visible text and diagrams."
        prompt = (
            f"{task_prompt}\n"
            f"Course: '{course_title}'.\n"
            f"Analyze the attached slide image carefully."
        )
        if document_text.strip():
            prompt += f"\n\nExtracted text (may be incomplete):\n{truncate_context(document_text, 2000)}"
    else:
        ctx = truncate_context(document_text)
        prompt = f"{task_prompt}\n\nCourse: '{course_title}'\n\nCONTENT:\n{ctx}"
    messages = [{"role": "system", "content": system}]
    messages.append(_build_user_message(prompt, page_images if use_vision else None))
    return messages


def learniq_summarize(course_title, document_text, page_images=None):
    task = (
        "Create a focused study summary of this page/module.\n"
        "Include: (1) Main topic in one sentence, (2) 4-6 bullet key points, "
        "(3) Important rules, standards, or constraints mentioned, (4) Key takeaway line.\n"
        "Max 350 words."
    )
    messages = _learniq_messages(course_title, document_text, task, page_images)
    return query_chat(messages, temperature=0.2, think=False)


def learniq_summarize_stream(course_title, document_text, page_images=None):
    task = (
        "Create a focused study summary of this page/module.\n"
        "Include: (1) Main topic in one sentence, (2) 4-6 bullet key points, "
        "(3) Important rules, standards, or constraints mentioned, (4) Key takeaway line.\n"
        "Max 350 words."
    )
    messages = _learniq_messages(course_title, document_text, task, page_images)
    yield from stream_chat(messages, temperature=0.2, think=False)


def learniq_flashcards(course_title, document_text, page_images=None):
    task = (
        "Create 6 study flashcards from this material.\n"
        'Return ONLY a JSON array: [{"front": "term", "back": "definition"}]'
    )
    messages = _learniq_messages(course_title, document_text, task, page_images)
    messages[0] = {"role": "system", "content": "You are LearnIQ. Return ONLY valid JSON. No markdown."}
    raw = query_chat(messages, temperature=0.2, think=False)
    return _normalize_flashcards(parse_json_response(raw) or [])


def learniq_sample_questions(course_title, document_text, page_images=None):
    task = (
        "Create 5 practice questions from this material for self-study.\n"
        "Mix multiple-choice and short-answer. Format exactly:\n\n"
        "**Question 1** (Multiple Choice)\n"
        "[question text]\n"
        "A) ... B) ... C) ... D) ...\n"
        "**Answer:** B — [one-line explanation]\n\n"
        "For short-answer use:\n"
        "**Question N** (Short Answer)\n"
        "[question]\n"
        "**Answer:** [expected answer] — [why it matters]\n"
    )
    messages = _learniq_messages(course_title, document_text, task, page_images)
    return query_chat(messages, temperature=0.35, think=False)


def learniq_sample_questions_stream(course_title, document_text, page_images=None):
    task = (
        "Create 5 practice questions from this material for self-study.\n"
        "Mix multiple-choice and short-answer. Use clear numbering and **Answer:** lines."
    )
    messages = _learniq_messages(course_title, document_text, task, page_images)
    yield from stream_chat(messages, temperature=0.35, think=False)


def learniq_chat(course_title, document_text, user_message, history=None, page_images=None):
    use_vision = needs_vision_fallback(document_text, page_images)
    ctx = truncate_context(document_text, max_chars=10000) if not use_vision else truncate_context(document_text, 2000)
    system = (
        f"You are LearnIQ, an AI tutor for TrainIQ's '{course_title}' module.\n"
        f"Answer ONLY from the course material{' and slide image' if use_vision else ''}. "
        f"If unsure, say so briefly.\n"
        + _learniq_format_rules()
        + f"\n\nCOURSE MATERIAL:\n{ctx}"
    )
    messages = [{"role": "system", "content": system}]
    if history:
        for turn in history[-8:]:
            role = turn.get("role", "user")
            if role == "assistant":
                role = "assistant"
            elif role != "system":
                role = "user"
            content = (turn.get("content") or "").strip()
            if content:
                messages.append({"role": role, "content": content})
    messages.append(_build_user_message(user_message, page_images if use_vision else None))
    return query_chat(messages, temperature=0.4, think=False)


def learniq_chat_stream(course_title, document_text, user_message, history=None, page_images=None):
    use_vision = needs_vision_fallback(document_text, page_images)
    ctx = truncate_context(document_text, max_chars=10000) if not use_vision else truncate_context(document_text, 2000)
    system = (
        f"You are LearnIQ, an AI tutor for TrainIQ's '{course_title}' module.\n"
        f"Answer ONLY from the course material{' and slide image' if use_vision else ''}. "
        f"If unsure, say so briefly.\n"
        + _learniq_format_rules()
        + f"\n\nCOURSE MATERIAL:\n{ctx}"
    )
    messages = [{"role": "system", "content": system}]
    if history:
        for turn in history[-8:]:
            role = turn.get("role", "user")
            if role not in ("assistant", "system"):
                role = "user"
            content = (turn.get("content") or "").strip()
            if content:
                messages.append({"role": role, "content": content})
    messages.append(_build_user_message(user_message, page_images if use_vision else None))
    yield from stream_chat(messages, temperature=0.4, think=False)


# ─── AnalyticsIQ ────────────────────────────────────────────────────────────

def analyticsiq_platform_summary(stats):
    """Executive summary for admin analytics dashboard."""
    system = (
        "You are AnalyticsIQ for TrainIQ admins. Summarize platform learning metrics "
        "in plain language for HR and L&D leaders. Be specific and actionable."
    )
    prompt = (
        f"Platform metrics (filtered period):\n"
        f"- Total users: {stats.get('total_users', 0)}\n"
        f"- Active users: {stats.get('active_users', 0)}\n"
        f"- Avg exam score: {stats.get('avg_exam_score', 0)}%\n"
        f"- Avg course progress: {stats.get('avg_course_progress', 0)}%\n"
        f"- Avg special exam score: {stats.get('special_avg_score', 0)}%\n"
        f"- Exam pass rate: {stats.get('pass_pct', 0)}% ({stats.get('passed_count', 0)} passed, "
        f"{stats.get('failed_count', 0)} failed)\n"
        f"- Special exam pass rate: {stats.get('sp_pass_pct', 0)}%\n"
        f"- Top departments by users: {stats.get('dept_labels', [])}\n"
        f"- Tasks assigned vs completed (by dept): {stats.get('task_depts', [])} — "
        f"assigned {stats.get('task_assigned', [])}, completed {stats.get('task_completed', [])}\n\n"
        f"Write exactly 4 short paragraphs:\n"
        f"1) Overall platform health\n"
        f"2) Strengths and positive trends\n"
        f"3) Risk areas or gaps needing attention\n"
        f"4) Three concrete admin actions for the next 2 weeks\n"
        f"No markdown headers. Use **bold** sparingly for key numbers only."
    )
    return query_local_model(prompt, system=system, temperature=0.35, think=False, timeout=180)


def analyticsiq_diagnose(user_name, scores_summary, incorrect_summary, available_courses):
    system = (
        "You are AnalyticsIQ for TrainIQ. Analyze learner performance and recommend "
        "specific courses from the provided list only. Write in plain language."
    )
    prompt = (
        f"Learner: {user_name}\n"
        f"Exam scores: {scores_summary}\n"
        f"Incorrect answer patterns: {incorrect_summary}\n"
        f"Available courses: {available_courses}\n\n"
        f"Write exactly 3 short paragraphs:\n"
        f"1) Key weaknesses with specific error patterns\n"
        f"2) Likely root causes\n"
        f"3) Recommended courses and next study actions (from the list above only)\n"
        f"No markdown headers or bullet lists."
    )
    return query_local_model(prompt, system=system, temperature=0.3, think=False, timeout=150)


# ─── CreatorIQ ──────────────────────────────────────────────────────────────

def creatoriq_outline(prompt_text, category=None, level=None):
    meta = ""
    if category:
        meta += f"Category: {category}. "
    if level:
        meta += f"Level: {level}. "
    system = "You are CreatorIQ for TrainIQ. Return ONLY valid JSON. No markdown."
    prompt = (
        f"{meta}Create a structured course outline for: {prompt_text}\n\n"
        f"Return ONLY JSON:\n"
        f'{{"title":"...","description":"...","subtopics":[{{"title":"...","lessons":["..."],'
        f'"checkpoint":"exam topic"}}],"estimated_minutes":60}}\n'
        f"Include 4-6 subtopics with 2-4 lessons each."
    )
    raw = query_local_model(prompt, system=system, temperature=0.3, think=False, timeout=180)
    return parse_json_response(raw)


# ─── ProctorIQ ──────────────────────────────────────────────────────────────

def compute_trust_score(events):
    """Algorithmic trust score (0-100). Higher = more trustworthy session."""
    if not events:
        return 100.0

    score = 100.0
    score -= events.get("tab_switches", 0) * 12
    score -= events.get("blur_events", 0) * 5
    score -= events.get("copy_attempts", 0) * 8
    score -= events.get("context_menu_attempts", 0) * 3
    score -= events.get("key_violations", 0) * 6

    time_spent = events.get("time_spent_seconds", 0)
    expected_time = events.get("expected_time_seconds", 0)
    if expected_time > 0 and time_spent > 0:
        ratio = time_spent / expected_time
        if ratio < 0.15:
            score -= 25
        elif ratio < 0.3:
            score -= 10

    return max(0.0, min(100.0, round(score, 1)))


def proctoriq_assess(events, exam_title):
    """Compute trust score and a short integrity narrative."""
    trust = compute_trust_score(events)
    system = "You are ProctorIQ for TrainIQ. Be brief and factual."
    prompt = (
        f"Exam: {exam_title}\nTrust Score: {trust}/100\n"
        f"Events: {json.dumps(events)}\n\n"
        f"In exactly 2 sentences, state risk level (Low/Medium/High) and admin action."
    )
    try:
        narrative = query_local_model(prompt, system=system, temperature=0.1, think=False, timeout=60)
    except ConnectionError:
        if trust >= 80:
            narrative = "Risk Level: Low. No admin review needed."
        elif trust >= 50:
            narrative = "Risk Level: Medium. Consider spot-checking this session."
        else:
            narrative = "Risk Level: High. Manual review recommended."
    return trust, narrative


# ─── Exam grading & question improvement ────────────────────────────────────

def grade_structured_answer(question_text, reference_answer, user_answer):
    """Return 0-100 score for a structured short-answer via local Gemma."""
    result = grade_structured_answer_rag(question_text, reference_answer, user_answer, context_snippets=None)
    if isinstance(result, dict):
        return max(0.0, min(100.0, float(result.get("score", 0))))
    return max(0.0, min(100.0, float(result)))


def grade_structured_answer_rag(question_text, reference_answer, user_answer, context_snippets=None):
    """Grade structured answer with optional study-material context. Returns dict or score."""
    system = "You are an exam grader for TrainIQ. Return ONLY valid JSON. No markdown."
    ctx = ""
    if context_snippets:
        ctx = f"\nRelevant study material:\n{context_snippets[:6000]}\n"
    prompt = (
        f"Question: {question_text}\n"
        f"Reference answer: {reference_answer}\n"
        f"Student answer: {user_answer}\n"
        f"{ctx}\n"
        f"Score 0-100 for correctness, completeness, and alignment with reference"
        f"{' and study material' if context_snippets else ''}.\n"
        f'Return ONLY JSON: {{"score": 85, "reason": "brief explanation", "similarity_notes": "..."}}'
    )
    raw = query_local_model(prompt, system=system, temperature=0.1, think=False, timeout=120)
    data = parse_json_response(raw)
    if isinstance(data, dict) and "score" in data:
        return data
    return {"score": 0.0, "reason": "Could not parse AI grade"}


def generate_exam_questions_rag(
    exam_title,
    level,
    material_text,
    count=5,
    question_types=None,
    *,
    chunk_pool=None,
    category_options=None,
    domain_hint=None,
    document_titles=None,
):
    """Generate exam questions grounded in study material (batched RAG + Gemma via Ollama)."""
    from utils.exam_rag import select_focus_chunks
    from utils.exam_ai import dedupe_questions, validate_questions

    types = question_types or ["single_choice", "structured"]
    count = max(1, min(int(count or 5), 20))
    pool = chunk_pool or []
    overview = truncate_context(material_text or "", max_chars=4000)
    categories = category_options or []

    try:
        all_questions = []
        batch_size = 2 if count > 2 else 1
        type_cycle = _question_type_cycle(types, count)
        batch_idx = 0
        attempts = 0
        max_attempts = count + 6

        while len(all_questions) < count and attempts < max_attempts:
            need = min(batch_size if batch_idx == 0 else 1, count - len(all_questions))
            batch_types = type_cycle[len(all_questions) : len(all_questions) + need]
            focus = select_focus_chunks(pool, batch_idx) if pool else {
                "title": (document_titles or ["Study material"])[0],
                "category": categories[0] if categories else "General",
                "text": overview,
            }
            excerpt = truncate_context(focus.get("text") or overview, max_chars=5500)
            batch = _generate_question_batch(
                exam_title=exam_title,
                level=level,
                focus_excerpt=excerpt,
                document_title=focus.get("title") or exam_title,
                document_category=focus.get("category"),
                count=need,
                question_types=batch_types or types,
                existing_questions=all_questions,
                category_options=categories,
                domain_hint=domain_hint,
                json_mode=True,
            )
            for q in batch:
                q["source_excerpt"] = excerpt
                if not q.get("category") and focus.get("category"):
                    q["category"] = focus.get("category")
            if batch:
                all_questions.extend(batch)
            batch_idx += 1
            attempts += 1

        cleaned = validate_questions(
            dedupe_questions(all_questions),
            types,
            category_options=categories,
            require_grounding=True,
        )
        if cleaned:
            return {
                "questions": cleaned[:count],
                "requested": count,
                "generated": len(cleaned[:count]),
            }
    except ConnectionError:
        return {"questions": [], "error": "Local AI is offline. Start Ollama and try again."}
    except Exception as e:
        logging.error("generate_exam_questions_rag failed: %s", e)

    return {
        "questions": [],
        "error": "Could not generate valid questions from the selected documents. Try fewer questions or one document.",
    }


def _question_type_cycle(types, total):
    """Round-robin question types for even distribution."""
    types = [t for t in (types or ["single_choice"]) if t] or ["single_choice"]
    return [types[i % len(types)] for i in range(total)]


def _generate_question_batch(
    exam_title,
    level,
    focus_excerpt,
    count,
    question_types,
    existing_questions=None,
    json_mode=True,
    document_title=None,
    document_category=None,
    category_options=None,
    domain_hint=None,
):
    """Generate a small batch from one RAG focus chunk — domain-agnostic."""
    type_str = ", ".join(question_types)
    avoid = ""
    if existing_questions:
        prev = [q.get("question_text", "")[:80] for q in existing_questions[-6:]]
        avoid = "\nDo NOT repeat these topics:\n- " + "\n- ".join(prev)

    cat_rule = ""
    if category_options:
        cat_rule = (
            f"- category (optional): best match from {', '.join(category_options)} — "
            "only if clearly applicable to the question\n"
        )
    elif document_category:
        cat_rule = f"- category (optional): use '{document_category}' when appropriate\n"

    system = (
        "You are CreatorIQ, an expert exam writer for TrainIQ — any industry or subject. "
        "Read the SOURCE EXCERPT carefully. Write questions ONLY from facts in that excerpt. "
        "Do not invent terms, processes, or answers not supported by the text. "
        "Return ONLY one valid JSON object. No markdown."
    )
    schema = (
        '{"questions":[{"question_text":"string","question_type":"single_choice|multiple_choice|structured",'
        '"choices":["opt1","opt2","opt3","opt4"],"correct_answer":"A","category":"optional topic label"}]}'
    )
    type_rules = (
        "Rules:\n"
        "- Base every question and answer strictly on the SOURCE EXCERPT below\n"
        "- single_choice: exactly 4 distinct choices from the material; correct_answer is one letter A-D\n"
        "- multiple_choice: 4 choices, correct_answer is comma letters e.g. A,C\n"
        "- structured: choices=[], correct_answer is a concise model answer (2-4 sentences) from the excerpt\n"
        f"{cat_rule}"
        "- Every question MUST end with ? and test understanding of the excerpt\n"
        "- Distractors must be plausible but wrong according to the excerpt\n"
        "- Never use generic filler like 'Option A' or 'All of the above' unless the excerpt supports it\n"
        "- No A)/B) prefixes in choice text\n"
        "- Use terminology exactly as it appears in the source when possible\n"
    )
    doc_line = document_title or exam_title
    hint_line = f"Context: {domain_hint}\n" if domain_hint else ""
    prompt = (
        f"Exam: {exam_title}\nDocument section: {doc_line}\nScope: {level}\n"
        f"{hint_line}"
        f"Generate exactly {count} question(s). Types for this batch: {type_str}\n"
        f"{type_rules}\n"
        f"SOURCE EXCERPT (generate ONLY from this text):\n{focus_excerpt}\n"
        f"{avoid}\n\n"
        f"Return ONLY JSON: {schema}"
    )

    for attempt in range(3):
        try:
            raw = query_local_model(
                prompt if not attempt else (
                    f"{prompt}\n\nPrevious output was invalid. "
                    f"Return ONLY valid JSON with exactly {count} question(s). Escape quotes in strings."
                ),
                system=system,
                temperature=0.2 if attempt else 0.3,
                think=False,
                timeout=120,
                json_mode=json_mode and attempt < 2,
            )
        except ConnectionError:
            raise
        except Exception as e:
            logging.warning("question batch attempt %s failed: %s", attempt + 1, e)
            continue

        questions = _coerce_exam_questions(parse_json_response(raw or ""))
        if len(questions) >= count:
            return questions[:count]
        if questions:
            return questions

    return []


def improve_exam_question(question_text, choices=None, question_type="single_choice"):
    """Clean grammar and verify choice formatting; returns dict with improved fields."""
    system = "You are CreatorIQ for TrainIQ exams. Return ONLY valid JSON. No markdown."
    choices_str = ", ".join(choices) if choices else ""
    prompt = (
        f"Question type: {question_type}\n"
        f"Question: {question_text}\n"
        f"Choices: {choices_str}\n\n"
        f"Fix grammar, clarity, and choice formatting. For multiple_choice, correct_answer may be comma-separated letters.\n"
        f'Return ONLY JSON: {{"question_text":"...","choices":["A text","B text"],'
        f'"correct_answer":"A or A,B","question_type":"{question_type}"}}'
    )
    raw = query_local_model(prompt, system=system, temperature=0.2, think=False, timeout=120)
    return parse_json_response(raw)

