"""Central security helpers — headers, production checks."""
from __future__ import annotations

import os

from utils.media_links import EMBED_FRAME_CSP


def validate_production_config(app) -> None:
    """Fail fast when critical secrets or dangerous ops settings are missing in production."""
    if os.getenv("FLASK_ENV", "development") == "development":
        return
    secret = app.config.get("SECRET_KEY") or ""
    if not secret or secret == "fallback-secret-key" or len(secret) < 32:
        raise RuntimeError("SECRET_KEY must be set to a random string of at least 32 characters in production.")

    import logging
    logger = logging.getLogger(__name__)

    if os.getenv("DB_OPTIMIZER_AUTO_APPLY", "").lower() in ("1", "true", "yes"):
        logger.error(
            "DB_OPTIMIZER_AUTO_APPLY is enabled in production — background index DDL may run during traffic."
        )

    if not (os.getenv("TRAINIQ_CEO_EMAIL") or "").strip():
        raise RuntimeError("TRAINIQ_CEO_EMAIL must be set in production.")

    if os.getenv("DB_INDEX_USE_CONCURRENTLY", "true").lower() in ("0", "false", "no"):
        logger.error(
            "DB_INDEX_USE_CONCURRENTLY=false in production — index applies may lock tables."
        )

    if os.getenv("RUN_SCHEDULER", "").lower() in ("1", "true", "yes") and not os.getenv("OPS_WORKER_MODE"):
        logger.warning(
            "RUN_SCHEDULER=true on a web worker — set RUN_SCHEDULER=false on web and use scripts/run_ops_worker.py."
        )

    if os.getenv("DB_BOOTSTRAP_ON_STARTUP", "").lower() in ("1", "true", "yes"):
        logger.warning(
            "DB_BOOTSTRAP_ON_STARTUP=true in production — schema guards run on every web worker boot; use deploy bootstrap instead."
        )

    if not (os.getenv("REDIS_URI") or "").strip() or (os.getenv("REDIS_URI") or "").startswith("memory://"):
        raise RuntimeError(
            "REDIS_URI must point to a real Redis instance in production (rate limits and ops cache)."
        )


def apply_security_headers(response, *, is_production: bool):
    """Apply defense-in-depth HTTP headers on every response."""
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["X-Permitted-Cross-Domain-Policies"] = "none"
    response.headers["Permissions-Policy"] = (
        "camera=(), microphone=(), geolocation=(), payment=(), usb=()"
    )
    if is_production:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    # CSP: allow CDNs + inline scripts used by templates; tighten over time.
    frame_src = " ".join(EMBED_FRAME_CSP)
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self' https://cdn.jsdelivr.net https://cdnjs.cloudflare.com 'unsafe-inline'; "
        "style-src 'self' https://fonts.googleapis.com https://cdnjs.cloudflare.com 'unsafe-inline'; "
        "font-src 'self' https://fonts.gstatic.com https://cdnjs.cloudflare.com data:; "
        "img-src 'self' data: blob: https:; "
        "connect-src 'self'; "
        f"frame-src {frame_src}; "
        "frame-ancestors 'none'; "
        "base-uri 'self'; "
        "form-action 'self'"
    )
    return response
