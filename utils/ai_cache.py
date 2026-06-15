"""Disk cache for LearnIQ summaries and flashcards."""
import hashlib
import json
import os
import time

CACHE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    "instance",
    "ai_cache",
)
CACHE_TTL = int(os.getenv("AI_CACHE_TTL", str(7 * 24 * 3600)))  # 7 days


def _ensure_dir():
    os.makedirs(CACHE_DIR, exist_ok=True)


def make_key(
    feature,
    course_id,
    file_id=None,
    page=None,
    asset_type=None,
    video_time=None,
    model=None,
):
    raw = (
        f"{feature}:{course_id}:{file_id or ''}:{page or 0}:"
        f"{asset_type or ''}:{video_time or ''}:{model or ''}"
    )
    return hashlib.sha256(raw.encode()).hexdigest()


def get(key):
    _ensure_dir()
    path = os.path.join(CACHE_DIR, f"{key}.json")
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            entry = json.load(f)
        if time.time() - entry.get("ts", 0) > CACHE_TTL:
            os.remove(path)
            return None
        return entry.get("data")
    except (json.JSONDecodeError, OSError):
        return None


def set(key, data):
    _ensure_dir()
    path = os.path.join(CACHE_DIR, f"{key}.json")
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"ts": time.time(), "data": data}, f)
    except OSError:
        pass
