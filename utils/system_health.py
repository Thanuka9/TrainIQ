"""Lightweight health checks for deployment and monitoring."""
from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)


def check_postgres() -> tuple[bool, str]:
    try:
        from extensions import db
        from sqlalchemy import text

        db.session.execute(text("SELECT 1"))
        return True, "ok"
    except Exception as exc:
        logger.warning("Postgres health check failed: %s", exc)
        return False, str(exc)


def check_redis() -> tuple[bool, str]:
    try:
        uri = (os.getenv("REDIS_URI") or "").strip()
        if not uri or uri.startswith("memory://"):
            return False, "not_configured"
        import redis

        redis.from_url(uri, socket_connect_timeout=2).ping()
        return True, "ok"
    except Exception as exc:
        logger.warning("Redis health check failed: %s", exc)
        return False, str(exc)


def check_mongodb() -> tuple[bool, str]:
    try:
        from mongodb_operations import get_mongo_connection

        client, db, _ = get_mongo_connection()
        if client is None or db is None:
            return False, "unavailable"
        client.admin.command("ping")
        return True, "ok"
    except Exception as exc:
        logger.warning("MongoDB health check failed: %s", exc)
        return False, str(exc)


def system_health() -> dict:
    pg_ok, pg_msg = check_postgres()
    mongo_ok, mongo_msg = check_mongodb()
    redis_ok, redis_msg = check_redis()
    healthy = pg_ok and redis_ok
    payload = {
        "status": "healthy" if healthy else "degraded",
        "postgres": {"ok": pg_ok, "detail": pg_msg},
        "mongodb": {"ok": mongo_ok, "detail": mongo_msg},
        "redis": {"ok": redis_ok, "detail": redis_msg},
    }
    try:
        from utils.db_optimizer_agent import latest_snapshot_summary
        from utils.mongo_platform import latest_mongo_summary
        from utils.ai_platform import latest_ai_summary

        db_monitor = latest_snapshot_summary()
        if db_monitor:
            payload["db_monitor"] = db_monitor
            if db_monitor.get("status") == "critical" and pg_ok:
                payload["status"] = "degraded"
        mongo_summary = latest_mongo_summary()
        if mongo_summary:
            payload["mongo_ops"] = mongo_summary
        ai_summary = latest_ai_summary()
        if ai_summary:
            payload["ai_ops"] = ai_summary
    except Exception as exc:
        logger.debug("Ops summary skipped: %s", exc)
    return payload
