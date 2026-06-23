"""Platform support-mode access: read-only default, explicit write elevation, audit."""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta

from flask import flash, redirect, request, session, url_for

logger = logging.getLogger(__name__)

SESSION_WRITE_ELEVATED_KEY = 'platform_support_write_elevated'
SESSION_WRITE_ELEVATED_AT_KEY = 'platform_support_write_elevated_at'


def support_write_elevation_ttl_minutes() -> int:
    return max(15, int(os.getenv('PLATFORM_SUPPORT_WRITE_TTL_MINUTES', '60')))


def is_in_support_mode() -> bool:
    return bool(session.get('platform_support'))


def is_support_write_elevated() -> bool:
    if not session.get(SESSION_WRITE_ELEVATED_KEY):
        return False
    raw = session.get(SESSION_WRITE_ELEVATED_AT_KEY)
    if not raw:
        return False
    try:
        started = datetime.fromisoformat(raw)
    except ValueError:
        return False
    if datetime.utcnow() - started > timedelta(minutes=support_write_elevation_ttl_minutes()):
        revoke_support_write_elevation()
        return False
    return True


def is_support_readonly() -> bool:
    return is_in_support_mode() and not is_support_write_elevated()


def can_support_view(user=None) -> bool:
    if not is_in_support_mode():
        return False
    from utils.tenant_utils import is_trainiq_staff

    if user is None:
        from flask_login import current_user

        user = current_user
    return is_trainiq_staff(user)


def can_support_write(user=None) -> bool:
    if not can_support_view(user):
        return False
    return is_support_write_elevated()


def begin_support_session(*, write_elevated: bool = False) -> None:
    """Start support mode with read-only default unless explicitly elevated."""
    from utils.support_session import mark_support_session_started

    mark_support_session_started()
    if write_elevated:
        elevate_support_write_access()
    else:
        revoke_support_write_elevation()


def elevate_support_write_access() -> None:
    session[SESSION_WRITE_ELEVATED_KEY] = True
    session[SESSION_WRITE_ELEVATED_AT_KEY] = datetime.utcnow().isoformat()


def revoke_support_write_elevation() -> None:
    session.pop(SESSION_WRITE_ELEVATED_KEY, None)
    session.pop(SESSION_WRITE_ELEVATED_AT_KEY, None)


def clear_support_access() -> None:
    from utils.support_session import clear_support_session_markers

    clear_support_session_markers()
    revoke_support_write_elevation()


def log_support_action(
    action: str,
    *,
    allowed: bool,
    view: str | None = None,
    extra: dict | None = None,
) -> None:
    if not is_in_support_mode():
        return
    try:
        from audit import log_event
        from flask_login import current_user

        log_event(
            'PLATFORM_SUPPORT_ACTION',
            user=current_user,
            action=action,
            allowed=allowed,
            view=view or request.endpoint,
            path=request.path,
            method=request.method,
            tenant_id=session.get('tenant_id'),
            tenant_name=session.get('tenant_name'),
            readonly=is_support_readonly(),
            write_elevated=is_support_write_elevated(),
            **(extra or {}),
        )
    except Exception as exc:
        logger.debug('[support_access] audit skipped: %s', exc)


def block_support_readonly_mutation(view_name: str | None = None):
    """Return a Flask response when a mutating request is blocked in readonly support."""
    if not is_in_support_mode():
        return None
    if request.method in ('GET', 'HEAD', 'OPTIONS'):
        return None
    if can_support_write():
        return None

    log_support_action('mutation_blocked', allowed=False, view=view_name)
    message = (
        'Support mode is read-only. Enable write access from the support banner '
        '(requires tenant management permission) to make changes.'
    )
    wants_json = (
        request.is_json
        or (request.content_type or '').startswith('application/json')
        or request.headers.get('X-Requested-With') == 'XMLHttpRequest'
    )
    if wants_json:
        from flask import jsonify

        return jsonify({'error': message}), 403
    flash(message, 'warning')
    return redirect(request.referrer or url_for('admin_routes.admin_dashboard'))


def audit_support_mutation_allowed(view_name: str | None = None) -> None:
    if not is_in_support_mode():
        return
    if request.method in ('GET', 'HEAD', 'OPTIONS'):
        return
    log_support_action('mutation_allowed', allowed=True, view=view_name)
