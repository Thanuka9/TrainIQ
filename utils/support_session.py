"""Platform support-mode session limits."""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta

from flask import flash, redirect, session, url_for

logger = logging.getLogger(__name__)

SESSION_STARTED_KEY = 'platform_support_started_at'


def support_session_ttl_hours() -> int:
    return max(1, int(os.getenv('PLATFORM_SUPPORT_TTL_HOURS', '2')))


def mark_support_session_started() -> None:
    session[SESSION_STARTED_KEY] = datetime.utcnow().isoformat()


def clear_support_session_markers() -> None:
    session.pop(SESSION_STARTED_KEY, None)
    from utils.support_access import revoke_support_write_elevation

    revoke_support_write_elevation()


def support_session_expired() -> bool:
    if not session.get('platform_support'):
        return False
    raw = session.get(SESSION_STARTED_KEY)
    if not raw:
        return False
    try:
        started = datetime.fromisoformat(raw)
    except ValueError:
        return False
    return datetime.utcnow() - started > timedelta(hours=support_session_ttl_hours())


def enforce_support_session_ttl():
    """Auto-exit customer support mode when TTL elapsed."""
    if not support_session_expired():
        return None

    from flask_login import current_user

    prev = session.get('tenant_name')
    session.pop('platform_support', None)
    from utils.support_access import clear_support_access

    clear_support_access()
    session.pop('is_super_admin', None)
    if current_user.is_authenticated:
        session['is_super_admin'] = bool(getattr(current_user, 'is_super_admin', False))

    logger.info('[platform_support] Session expired for %s (was in %s)', getattr(current_user, 'employee_email', '?'), prev)
    flash(
        f'Support mode for {prev or "customer org"} expired after {support_session_ttl_hours()}h. '
        'Re-enter from the platform console if needed.',
        'warning',
    )
    return redirect(url_for('platform_routes.platform_dashboard'))
