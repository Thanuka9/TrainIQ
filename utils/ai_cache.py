"""Disk cache for LearnIQ summaries and flashcards (disk or S3 backend)."""

import hashlib

import os

import time

from collections import Counter



from utils.ai_cache_storage import get_cache_storage



CACHE_DIR = os.path.join(

    os.path.dirname(os.path.dirname(__file__)),

    "instance",

    "ai_cache",

)

CACHE_TTL = int(os.getenv("AI_CACHE_TTL", str(7 * 24 * 3600)))  # 7 days

CACHE_MAX_MB = int(os.getenv("OPS_AI_CACHE_MAX_MB", "512"))





def _ensure_dir():

    os.makedirs(CACHE_DIR, exist_ok=True)





def _storage():

    return get_cache_storage()





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





def get_cache_stats() -> dict:

    """Detailed cache statistics for ops dashboard."""

    storage = _storage()

    keys = storage.list_keys()

    total_bytes = 0

    expired = 0

    by_feature: Counter = Counter()

    now = time.time()

    oldest_ts = None

    newest_ts = None



    for key in keys:

        entry = storage.read(key)

        if not entry:

            continue

        try:

            size = len(str(entry))

            total_bytes += size

            ts = entry.get("ts", 0)

            if oldest_ts is None or ts < oldest_ts:

                oldest_ts = ts

            if newest_ts is None or ts > newest_ts:

                newest_ts = ts

            if entry.get("feature"):

                by_feature[entry["feature"]] += 1

            if now - ts > CACHE_TTL:

                expired += 1

        except Exception:

            pass



    total_mb = round(total_bytes / (1024 * 1024), 2)

    desc = storage.describe()

    return {

        "path": desc.get("path") or desc.get("bucket", CACHE_DIR),

        "backend": desc.get("backend", "disk"),

        "files": len(keys),

        "expired_estimate": expired,

        "total_mb": total_mb,

        "max_mb": CACHE_MAX_MB,

        "over_capacity": total_mb > CACHE_MAX_MB,

        "by_feature": dict(by_feature.most_common(20)),

        "oldest_age_hours": round((now - oldest_ts) / 3600, 1) if oldest_ts else None,

        "newest_age_hours": round((now - newest_ts) / 3600, 1) if newest_ts else None,

    }





def trim_to_capacity(max_mb: int | None = None) -> dict:

    """Remove oldest cache entries until total size is under max_mb."""

    storage = _storage()

    limit_mb = max_mb if max_mb is not None else CACHE_MAX_MB

    limit_bytes = limit_mb * 1024 * 1024



    entries = []

    for key in storage.list_keys():

        entry = storage.read(key)

        if not entry:

            continue

        ts = entry.get("ts", 0)

        size = len(str(entry))

        entries.append((key, ts, size))



    total = sum(e[2] for e in entries)

    if total <= limit_bytes:

        return {"removed": 0, "freed_mb": 0, "remaining_mb": round(total / (1024 * 1024), 2)}



    entries.sort(key=lambda e: e[1])

    removed = freed = 0

    for key, _ts, size in entries:

        if total <= limit_bytes:

            break

        if storage.delete(key):

            total -= size

            freed += size

            removed += 1



    return {

        "removed": removed,

        "freed_mb": round(freed / (1024 * 1024), 2),

        "remaining_mb": round(total / (1024 * 1024), 2),

    }





def get(key):

    entry = _storage().read(key)

    if not entry:

        return None

    if time.time() - entry.get("ts", 0) > CACHE_TTL:

        _storage().delete(key)

        return None

    return entry.get("data")





def set(key, data, feature=None):

    try:

        _storage().write(key, {"ts": time.time(), "feature": feature, "data": data})

        stats = get_cache_stats()

        if stats["over_capacity"]:

            trim_to_capacity()

    except Exception:
        pass

