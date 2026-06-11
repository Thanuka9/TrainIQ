"""Per-user AI rate limiting (works without Redis)."""
import os
import time
from collections import defaultdict, deque
from functools import wraps
from threading import Lock

from flask import jsonify, request, session

_PER_HOUR = int(os.getenv("AI_RATE_LIMIT_HOUR", "20"))
_PER_MINUTE = int(os.getenv("AI_RATE_LIMIT_MINUTE", "5"))

_buckets = defaultdict(deque)
_lock = Lock()


def _user_key():
    return str(session.get("user_id") or request.remote_addr or "anon")


def check_ai_rate_limit(user_key=None, cost=1):
    user_key = user_key or _user_key()
    now = time.time()
    with _lock:
        q = _buckets[user_key]
        while q and now - q[0] > 3600:
            q.popleft()
        recent_min = sum(1 for t in q if now - t < 60)
        if len(q) + cost > _PER_HOUR:
            retry = int(3600 - (now - q[0])) + 1 if q else 3600
            return False, retry
        if recent_min + cost > _PER_MINUTE:
            oldest_in_min = next((t for t in q if now - t < 60), now)
            return False, int(60 - (now - oldest_in_min)) + 1
        for _ in range(cost):
            q.append(now)
        return True, 0


def ai_rate_limited(cost=1):
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            ok, retry = check_ai_rate_limit(cost=cost)
            if not ok:
                return jsonify({
                    "error": f"AI rate limit reached ({_PER_HOUR}/hr). Retry in {retry}s.",
                    "retry_after": retry,
                }), 429
            return f(*args, **kwargs)
        return wrapper
    return decorator
