# TrainIQ SaaS — AI Integration & Marketing Strategy

TrainIQ positions itself as a leading-edge AI training platform by weaving four branded AI capabilities directly into core workflows — **without any cloud API keys**. All features run on a **local Ollama instance** with **Gemma 4** (default: `gemma4:e4b`).

## Architecture: Local AI Engine (No API Keys)

| Component | Technology |
|-----------|------------|
| Runtime | [Ollama](https://ollama.com) on `localhost:11434` |
| Default model | `gemma4:e4b` (auto-detected from installed models) |
| API | Ollama `/api/chat` with `think: false` for fast responses |
| Context window | Up to 12K chars of course text (128K token model) |
| Python bridge | `utils/local_ai.py` |
| Fallback | Graceful error messages when Ollama or model is missing |

```bash
# One-time setup (matches your local install)
ollama pull gemma4:e4b
ollama serve
```

---

## 1. LearnIQ — AI Study Tutor & Document Summarizer

**Marketing hook:** *"LearnIQ: A personal AI tutor embedded in every study module."*

**How it works:**
- Inline AI sidebar on the course content viewer (`course_content.html`)
- Extracts text from PDF/DOCX/PPTX/TXT files stored in GridFS
- One-click **Summarize** and **Flashcards** actions
- Interactive chat grounded in the current module's content

**API endpoints:**
- `GET /study_materials/ai/status`
- `POST /study_materials/ai/summarize/<course_id>`
- `POST /study_materials/ai/flashcards/<course_id>`
- `POST /study_materials/ai/chat/<course_id>`

---

## 2. AnalyticsIQ — Smart Performance Insights

**Marketing hook:** *"AnalyticsIQ: Predictive diagnostics that pinpoint learning gaps in real-time."*

**How it works:**
- Analyzes `UserScore` history and `IncorrectAnswer` logs
- Generates natural-language weakness diagnoses via local Gemma
- Recommends courses from the existing `StudyMaterial` catalog

**API endpoint:**
- `GET /ai/performance-insights` (Dashboard "Analyze" button)

---

## 3. ProctorIQ — Privacy-First Exam Integrity

**Marketing hook:** *"ProctorIQ: Privacy-first, AI-driven exam integrity checks."*

**How it works:**
- Tracks tab switches, blur events, copy attempts, key violations during exams
- Computes an algorithmic **Trust Score** (0–100) on submission
- Optional AI narrative for admin review
- Flags sessions with trust score < 70 on the Admin **ProctorIQ Review** page

**Data stored:** `user_scores.trust_score`, `proctor_events`, `proctor_narrative`

---

## 4. CreatorIQ — AI Course Authoring Wizard

**Marketing hook:** *"CreatorIQ: AI-powered course authoring wizard."*

**How it works:**
- Admin enters a prompt (e.g. "HIPAA VOB Level 2 course outline")
- Local Gemma returns structured JSON: title, description, subtopics, lessons, checkpoints
- Displayed on Admin → Courses page for copy-paste into the upload workflow

**API endpoint:**
- `POST /admin/courses/generate-outline`

---

## Implementation Roadmap

| Phase | Feature | Status |
|-------|---------|--------|
| 1 | AI Exam Question Generation (CreatorIQ-adjacent) | ✅ Complete |
| 2 | LearnIQ — Summarize, Flashcards, Chat | ✅ Complete |
| 3 | AnalyticsIQ — Performance Diagnostics | ✅ Complete |
| 4 | ProctorIQ — Trust Score + Admin Review | ✅ Complete |
| 5 | CreatorIQ — Course Outline Wizard | ✅ Complete |

---

## Environment Variables

```env
OLLAMA_BASE=http://127.0.0.1:11434
OLLAMA_MODEL=gemma4:e4b
OLLAMA_TIMEOUT=120
OLLAMA_CONTEXT_CHARS=12000
```
