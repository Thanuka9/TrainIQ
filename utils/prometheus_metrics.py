"""Optional Prometheus metrics exposition for the Flask monolith."""
from __future__ import annotations

import logging
import os
import time
from typing import Any

logger = logging.getLogger(__name__)

_METRICS_ENABLED = os.getenv('PROMETHEUS_METRICS_ENABLED', 'false').lower() in ('1', 'true', 'yes')
_METRICS_TOKEN = (os.getenv('PROMETHEUS_METRICS_TOKEN') or '').strip()

_registry = None
_counters: dict[str, Any] = {}
_histograms: dict[str, Any] = {}


def metrics_enabled() -> bool:
    return _METRICS_ENABLED


def _init_registry():
    global _registry
    if _registry is not None:
        return _registry
    try:
        from prometheus_client import CollectorRegistry, Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST

        _registry = CollectorRegistry(auto_describe=True)
        _counters['http_requests'] = Counter(
            'trainiq_http_requests_total',
            'HTTP requests',
            ['method', 'endpoint', 'status'],
            registry=_registry,
        )
        _counters['login_failures'] = Counter(
            'trainiq_login_failures_total',
            'Failed login attempts',
            registry=_registry,
        )
        _counters['stripe_webhooks'] = Counter(
            'trainiq_stripe_webhooks_total',
            'Stripe webhook events',
            ['event_type', 'outcome'],
            registry=_registry,
        )
        _histograms['request_duration'] = Histogram(
            'trainiq_http_request_duration_seconds',
            'HTTP request duration',
            ['method', 'endpoint'],
            registry=_registry,
        )
        _registry._generate_latest = generate_latest  # type: ignore[attr-defined]
        _registry._content_type = CONTENT_TYPE_LATEST  # type: ignore[attr-defined]
    except ImportError:
        logger.info('[prometheus] prometheus_client not installed — metrics disabled')
        _registry = False
    return _registry


def inc_login_failure() -> None:
    if not metrics_enabled():
        return
    reg = _init_registry()
    if reg and 'login_failures' in _counters:
        _counters['login_failures'].inc()


def inc_stripe_webhook(event_type: str, outcome: str) -> None:
    if not metrics_enabled():
        return
    reg = _init_registry()
    if reg and 'stripe_webhooks' in _counters:
        _counters['stripe_webhooks'].labels(event_type=event_type, outcome=outcome).inc()


def observe_request(method: str, endpoint: str, status: int, duration_s: float) -> None:
    if not metrics_enabled():
        return
    reg = _init_registry()
    if not reg:
        return
    ep = endpoint or 'unknown'
    if 'http_requests' in _counters:
        _counters['http_requests'].labels(method=method, endpoint=ep, status=str(status)).inc()
    if 'request_duration' in _histograms:
        _histograms['request_duration'].labels(method=method, endpoint=ep).observe(duration_s)


def metrics_response():
    """Return (body, content_type) for /metrics or None if disabled."""
    if not metrics_enabled():
        return None
    reg = _init_registry()
    if not reg:
        return None
    from prometheus_client import generate_latest, CONTENT_TYPE_LATEST

    return generate_latest(reg), CONTENT_TYPE_LATEST


def authorize_metrics_request(auth_header: str | None) -> bool:
    if not _METRICS_TOKEN:
        return os.getenv('FLASK_ENV', 'development').lower() not in ('production', 'prod')
    token = (auth_header or '').replace('Bearer ', '').strip()
    return token == _METRICS_TOKEN
