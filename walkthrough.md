# TrainIQ AI Walkthrough — Local Gemma 4 via Ollama

This guide documents how to set up, verify, and use TrainIQ's four AI features with **zero API keys**.

## Prerequisites

1. Install [Ollama](https://ollama.com/download) (v0.20+ for Gemma 4 support)
2. Pull Gemma 4 E4B (balanced default — matches most workstations):
   ```bash
   ollama pull gemma4:e4b
   ```
3. Ensure Ollama is running (open the Ollama app on Windows, or `ollama serve`)
4. Run the database migration for ProctorIQ fields:
   ```bash
   flask db upgrade
   ```

## Verify Local AI Engine

```bash
python -c "from utils.local_ai import get_ai_status; import json; print(json.dumps(get_ai_status(), indent=2))"
```

Expected when ready:
```json
{
  "available": true,
  "model_ready": true,
  "model": "gemma4:e4b",
  "resolved_model": "gemma4:e4b",
  "engine": "ollama",
  "message": "Ready — using gemma4:e4b (no API keys)"
}
```

Quick generation test (first run may take 1–2 minutes while the model loads):
```bash
python -c "from utils.local_ai import query_local_model; print(query_local_model('Say OK in one word.', think=False))"
```

## Why Gemma 4 (not Gemma 2)?

| | Gemma 2 | Gemma 4 E4B (your install) |
|--|---------|----------------------------|
| Context | 8K | **128K** |
| Quality | Good | Better reasoning & instruction following |
| Ollama tag | `gemma2` | `gemma4:e4b` |
| TrainIQ default | — | **`gemma4:e4b`** |

TrainIQ auto-detects installed models. If `gemma4:e4b` is present, it is used automatically.

## Feature Walkthroughs

### LearnIQ (Study Viewer)

1. Log in and open any course with PDF/DOCX content
2. Click the **LearnIQ** floating button (bottom-right)
3. Use **Summarize**, **Flashcards**, or chat about the module
4. Status bar shows: `Powered by local gemma4:e4b (no API keys)`

### AnalyticsIQ (Dashboard)

1. Go to **Dashboard** → **AnalyticsIQ Insights**
2. Click **Analyze** — Gemma 4 reviews scores and incorrect answers

### ProctorIQ (Exams)

1. Take a proctored exam — events are tracked automatically
2. Trust Score stored on submit
3. Admins review flagged sessions at **Admin → ProctorIQ Review**

### CreatorIQ (Admin Courses)

1. **Admin → Courses** → enter a prompt → **Generate Outline**

### AI Exam Generation

1. **Admin → Exams → Edit** → **AI Generate Questions**

## Improvements Built In

- **Streaming UI** — summaries and chat stream tokens live via SSE (`/ai/stream/...`)
- **Response caching** — summaries & flashcards cached per `course + page` in `instance/ai_cache/` (7-day TTL)
- **CreatorIQ Apply** — "Apply to Upload Form" pre-fills title, description, hours, and subtopics
- **Background jobs** — AnalyticsIQ & CreatorIQ run async; poll `GET /ai/jobs/<job_id>`
- **Gemma 4 vision** — when PDF text is sparse, the current slide canvas is sent to `gemma4:e4b`
- **Rate limiting** — 20 requests/hour, 5/minute per user (configurable via `.env`)
- **Chat API** (`/api/chat`) with **`think: false`** for faster local inference
- **Auto model resolution** — uses your installed `gemma4:e4b`

## Troubleshooting

| Issue | Fix |
|-------|-----|
| "Ollama is not running" | Open the Ollama desktop app |
| "Model not found" | `ollama pull gemma4:e4b` |
| Very slow first response | Normal — model loads into VRAM/RAM on first use (~1–2 min) |
| Timeout errors | Increase `OLLAMA_TIMEOUT=180` in `.env` |
| Wrong model used | Set `OLLAMA_MODEL=gemma4:e4b` explicitly |

## Environment Variables

```env
OLLAMA_BASE=http://127.0.0.1:11434
OLLAMA_MODEL=gemma4:e4b
OLLAMA_TIMEOUT=120
OLLAMA_CONTEXT_CHARS=12000
```

## System & UI Updates (June 2026)

### 1. Database Schema Upgrade
- Changed `correct_answer` column type in the `questions` table from `VARCHAR(255)` to `TEXT` to support long AI-generated structured question keys. This prevents `StringDataRightTruncation` errors when saving complex questions.

### 2. User Comparison Dashboard
- **Interactive Team Member Grid**: Allows admins to select users by clicking visually rich profile cards.
- **Search Filtering**: Real-time filtering by name, email, department, or job title.
- **Floating Compare Dashboard**: A sliding bottom bar displaying selected users side-by-side with a VS badge before submitting.
- **Comparative Metric Matrix**: Renders inline progress tracks and color-coded delta badges showing which user is leading in each metric.
