"""Webhook/email alerts when platform ops status is critical."""
from __future__ import annotations

import json
import logging
import os
import time
import urllib.request
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)

_COOLDOWN_FILE = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    'instance',
    'ops_alert_cooldown.json',
)


def _cooldown_seconds() -> int:
    return max(300, int(os.getenv('PLATFORM_OPS_ALERT_COOLDOWN_SECONDS', '3600')))


def _email_alerts_enabled() -> bool:
    return os.getenv('PLATFORM_OPS_ALERT_EMAIL', 'true').lower() in ('1', 'true', 'yes')


def _in_cooldown(alert_key: str) -> bool:
    from utils.ops_cache import _get_redis

    r = _get_redis()
    if r is not None:
        try:
            return bool(r.get(f'trainiq:ops:alert_cd:{alert_key}'))
        except Exception:
            pass

    try:
        if os.path.isfile(_COOLDOWN_FILE):
            with open(_COOLDOWN_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
            last = float(data.get(alert_key, 0))
            return (time.time() - last) < _cooldown_seconds()
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        pass
    return False


def _mark_cooldown(alert_key: str) -> None:
    from utils.ops_cache import _get_redis

    r = _get_redis()
    if r is not None:
        try:
            r.setex(f'trainiq:ops:alert_cd:{alert_key}', _cooldown_seconds(), '1')
            return
        except Exception:
            pass

    try:
        os.makedirs(os.path.dirname(_COOLDOWN_FILE), exist_ok=True)
        data = {}
        if os.path.isfile(_COOLDOWN_FILE):
            with open(_COOLDOWN_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
        data[alert_key] = time.time()
        with open(_COOLDOWN_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f)
    except OSError as exc:
        logger.debug('[ops_alerts] cooldown file write failed: %s', exc)


def _send_ceo_email_alert(payload: dict[str, Any], alert_key: str) -> bool:
    if not _email_alerts_enabled():
        return False
    try:
        from flask_mail import Message

        from extensions import mail
        from utils.platform_ceo import PLATFORM_CEO_EMAIL

        if not PLATFORM_CEO_EMAIL:
            return False
        subject = f'[TrainIQ Ops] Critical platform health ({payload.get("source", "ops")})'
        body = json.dumps(payload, indent=2, default=str)
        msg = Message(subject=subject, recipients=[PLATFORM_CEO_EMAIL], body=body)
        mail.send(msg)
        _mark_cooldown(alert_key)
        logger.info('[ops_alerts] Critical alert emailed to CEO for source=%s', payload.get('source'))
        return True
    except Exception as exc:
        logger.warning('[ops_alerts] CEO email failed: %s', exc)
        return False


def _post_webhook(webhook: str, payload: dict[str, Any]) -> bool:
    body = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(
        webhook,
        data=body,
        headers={'Content-Type': 'application/json'},
        method='POST',
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return 200 <= resp.status < 300


def maybe_send_ops_alert(
    *,
    status: str,
    source: str,
    detail: dict[str, Any] | None = None,
) -> bool:
    """Notify via webhook and/or CEO email when status is critical (rate-limited)."""
    if (status or '').lower() != 'critical':
        return False

    alert_key = f'critical:{source}'
    if _in_cooldown(alert_key):
        return False

    payload = {
        'event': 'platform_ops_critical',
        'status': status,
        'source': source,
        'timestamp': datetime.utcnow().isoformat() + 'Z',
        'detail': detail or {},
    }

    webhook = (os.getenv('PLATFORM_OPS_ALERT_WEBHOOK') or '').strip()
    if webhook:
        try:
            if _post_webhook(webhook, payload):
                _mark_cooldown(alert_key)
                logger.info('[ops_alerts] Critical webhook sent for source=%s', source)
                return True
        except Exception as exc:
            logger.warning('[ops_alerts] Webhook failed: %s', exc)

    return _send_ceo_email_alert(payload, alert_key)
