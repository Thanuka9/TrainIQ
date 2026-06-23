"""Optional IP allowlist for TrainIQ platform console (/platform/*)."""
from __future__ import annotations

import logging
import os

from flask import flash, redirect, request, url_for
from flask_login import current_user

logger = logging.getLogger(__name__)


def _allowed_ips() -> set[str]:
    raw = (os.getenv('TRAINIQ_PLATFORM_IP_ALLOWLIST') or '').strip()
    if not raw:
        return set()
    return {ip.strip() for ip in raw.split(',') if ip.strip()}


def client_ip() -> str:
    forwarded = (request.headers.get('X-Forwarded-For') or '').strip()
    if forwarded:
        return forwarded.split(',')[0].strip()
    return (request.remote_addr or '').strip()


def platform_ip_allowlist_enabled() -> bool:
    return bool(_allowed_ips())


def is_ip_allowed(addr: str | None = None) -> bool:
    allowed = _allowed_ips()
    if not allowed:
        return True
    addr = (addr or client_ip()).strip()
    return addr in allowed


def enforce_platform_ip_allowlist():
    """Block platform staff from /platform/* when IP is not on the allowlist."""
    if not request.path.startswith('/platform'):
        return None

    from utils.tenant_utils import is_trainiq_staff

    if not current_user.is_authenticated or not is_trainiq_staff():
        return None
    if is_ip_allowed():
        return None

    logger.warning(
        '[platform_ip] Denied %s from %s',
        getattr(current_user, 'employee_email', '?'),
        client_ip(),
    )
    flash('Platform console access is restricted from this network.', 'error')
    return redirect(url_for('general_routes.dashboard'))
