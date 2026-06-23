"""Request an application restart (Azure App Service Kudu or webhook)."""
from __future__ import annotations

import logging
import os
import threading
from typing import Any

logger = logging.getLogger(__name__)


def request_app_restart(*, delay_seconds: float = 2.0) -> tuple[bool, str, dict[str, Any]]:
    """
    Restart the hosting app. Returns (ok, message, detail).
    Uses PLATFORM_RESTART_WEBHOOK_URL first, then Azure Kudu SCM API.
    """
    webhook = (os.getenv('PLATFORM_RESTART_WEBHOOK_URL') or '').strip()
    site = (os.getenv('WEBSITE_SITE_NAME') or os.getenv('AZURE_WEBAPP_NAME') or '').strip()
    user = (os.getenv('AZURE_WEBSITE_PUBLISH_USER') or '').strip()
    password = (os.getenv('AZURE_WEBSITE_PUBLISH_PASSWORD') or '').strip()

    detail: dict[str, Any] = {'method': None}

    try:
        import requests
    except ImportError:
        return False, 'requests package required for remote restart.', detail

    if webhook:
        try:
            resp = requests.post(webhook, timeout=45)
            detail.update(method='webhook', status_code=resp.status_code)
            if resp.ok:
                return True, 'Restart webhook accepted — app will restart shortly.', detail
            return False, f'Restart webhook failed (HTTP {resp.status_code}).', detail
        except Exception as exc:
            logger.error('[restart] webhook failed: %s', exc)
            return False, f'Restart webhook error: {exc}', detail

    if site and user and password:
        url = f'https://{site}.scm.azurewebsites.net/api/app/restart'
        try:
            resp = requests.post(url, auth=(user, password), timeout=60)
            detail.update(method='azure_kudu', status_code=resp.status_code, site=site)
            if resp.status_code in (200, 202, 204) or resp.ok:
                return True, 'Azure app restart requested — site will reload in ~30 seconds.', detail
            return False, f'Azure restart failed (HTTP {resp.status_code}).', detail
        except Exception as exc:
            logger.error('[restart] Azure Kudu failed: %s', exc)
            return False, f'Azure restart error: {exc}', detail

    return (
        False,
        'Restart skipped — set PLATFORM_RESTART_WEBHOOK_URL or Azure publish credentials '
        '(AZURE_WEBSITE_PUBLISH_USER / AZURE_WEBSITE_PUBLISH_PASSWORD + WEBSITE_SITE_NAME).',
        detail,
    )


def schedule_app_restart(delay_seconds: float = 2.0) -> tuple[bool, str]:
    """Fire-and-forget restart so the HTTP response can finish first."""
    ok, msg, _detail = request_app_restart(delay_seconds=0)
    if not ok:
        return False, msg

    def _worker():
        request_app_restart(delay_seconds=0)
        logger.info('[restart] scheduled restart dispatched')

    threading.Timer(max(0.5, delay_seconds), _worker).start()
    return True, f'App restart scheduled in {delay_seconds:.0f}s (after maintenance completes).'
