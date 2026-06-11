"""Central security helpers — headers, production checks."""
from __future__ import annotations

import os


def validate_production_config(app) -> None:
    """Fail fast when critical secrets are missing in production."""
    if os.getenv("FLASK_ENV", "development") == "development":
        return
    secret = app.config.get("SECRET_KEY") or ""
    if not secret or secret == "fallback-secret-key" or len(secret) < 32:
        raise RuntimeError("SECRET_KEY must be set to a random string of at least 32 characters in production.")


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
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self' https://cdn.jsdelivr.net https://cdnjs.cloudflare.com 'unsafe-inline'; "
        "style-src 'self' https://fonts.googleapis.com https://cdnjs.cloudflare.com 'unsafe-inline'; "
        "font-src 'self' https://fonts.gstatic.com https://cdnjs.cloudflare.com data:; "
        "img-src 'self' data: blob: https:; "
        "connect-src 'self'; "
        "frame-ancestors 'none'; "
        "base-uri 'self'; "
        "form-action 'self'"
    )
    return response
