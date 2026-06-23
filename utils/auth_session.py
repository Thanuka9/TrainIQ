"""Shared login session + 2FA gate for password and SSO flows."""
from __future__ import annotations

import logging
import os

from flask import redirect, session, url_for, flash
from flask_login import login_user
from sqlalchemy.exc import SQLAlchemyError

logger = logging.getLogger(__name__)


def platform_staff_2fa_required() -> bool:
    return os.getenv('PLATFORM_STAFF_REQUIRE_2FA', 'true').lower() in ('1', 'true', 'yes')


def user_requires_2fa(user) -> bool:
    """True when tenant 2FA is on or platform staff policy requires it."""
    from utils.tenant_utils import is_trainiq_staff

    tenant = getattr(user, 'tenant', None)
    if tenant and getattr(tenant, 'enable_2fa', False):
        return True
    if platform_staff_2fa_required() and is_trainiq_staff(user):
        return True
    return False


def user_requires_email_2fa(user) -> bool:
    """Email OTP when 2FA required but TOTP not enrolled."""
    from utils.totp_2fa import user_has_totp

    return user_requires_2fa(user) and not user_has_totp(user)


def prepare_login_session(
    user,
    tenant,
    *,
    platform_support: bool = False,
) -> None:
    """Populate Flask session before 2FA verification or login_user."""
    from utils.tenant_utils import set_active_tenant_session

    session['user_id'] = user.id
    session['is_super_admin'] = user.is_super_admin
    session['role_id'] = user.roles[0].id if user.roles else None
    session['designation_id'] = user.designation_id
    if platform_support:
        set_active_tenant_session(tenant, platform_support=True)
        from utils.support_access import begin_support_session

        begin_support_session(write_elevated=False)
    else:
        set_active_tenant_session(tenant, platform_support=False)
    session['tenant_name'] = session.get('tenant_name') or (
        user.tenant.name if user.tenant else tenant.name
    )
    session.permanent = True


def complete_login_or_2fa(user, *, login_method: str = 'password'):
    """
    Route to TOTP, email 2FA, or complete login.
    Returns a Flask response.
    """
    from auth_routes import _redirect_after_login, _send_2fa_email
    from extensions import db
    from utils.totp_2fa import user_has_totp

    if user_has_totp(user):
        session['pending_login_method'] = login_method
        session['pending_2fa_mode'] = 'totp'
        flash('Enter the code from your authenticator app.', 'info')
        return redirect(url_for('auth_routes.verify_totp'))

    if user_requires_email_2fa(user):
        try:
            _send_2fa_email(user)
        except SQLAlchemyError as exc:
            db.session.rollback()
            logger.error('DB error during 2FA setup: %s', exc)
            flash('Server error. Please try again.', 'error')
            return redirect(url_for('auth_routes.login'))
        session['pending_login_method'] = login_method
        session['pending_2fa_mode'] = 'email'
        flash('2FA code sent. Please verify.', 'info')
        return redirect(url_for('auth_routes.verify_2fa'))

    login_user(user)
    logger.info('User %s logged in via %s', user.id, login_method)
    return _redirect_after_login(user)
