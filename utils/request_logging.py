"""Request correlation IDs and optional JSON-friendly log context."""
from __future__ import annotations

import logging
import os
import uuid

from flask import g, request


class RequestIdFilter(logging.Filter):
    def filter(self, record):
        try:
            record.request_id = getattr(g, 'request_id', '-')
        except RuntimeError:
            record.request_id = '-'
        return True


def init_request_logging(app) -> None:
    """Attach request IDs and a logging filter."""
    fmt = '%(asctime)s %(levelname)s [%(request_id)s] %(name)s: %(message)s'
    if os.getenv('LOG_JSON', 'false').lower() in ('1', 'true', 'yes'):
        fmt = '%(asctime)s %(levelname)s request_id=%(request_id)s %(name)s %(message)s'

    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(fmt))
    handler.addFilter(RequestIdFilter())

    root = logging.getLogger()
    if not any(isinstance(h, logging.StreamHandler) and h.formatter for h in root.handlers):
        root.addHandler(handler)
        root.setLevel(logging.INFO)

    @app.before_request
    def _assign_request_id():
        g.request_id = request.headers.get('X-Request-ID') or uuid.uuid4().hex[:16]
        g._request_started_at = __import__('time').monotonic()

    @app.after_request
    def _log_request_metrics(response):
        try:
            from utils.prometheus_metrics import observe_request

            started = getattr(g, '_request_started_at', None)
            duration = (__import__('time').monotonic() - started) if started else 0.0
            observe_request(
                request.method,
                request.endpoint or 'unknown',
                response.status_code,
                duration,
            )
        except Exception:
            pass
        return response
