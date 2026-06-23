"""TOTP authenticator support (optional upgrade over email OTP)."""
from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)


def totp_available() -> bool:
    try:
        import pyotp  # noqa: F401
        return True
    except ImportError:
        return False


def generate_totp_secret() -> str:
    import pyotp

    return pyotp.random_base32()


def provisioning_uri(*, secret: str, email: str, issuer: str | None = None) -> str:
    import pyotp

    name = issuer or os.getenv('TRAINIQ_TOTP_ISSUER', 'TrainIQ')
    return pyotp.totp.TOTP(secret).provisioning_uri(name=email, issuer_name=name)


def verify_totp_code(secret: str, code: str, *, valid_window: int = 1) -> bool:
    if not secret or not code:
        return False
    try:
        import pyotp

        totp = pyotp.TOTP(secret)
        return totp.verify((code or '').strip().replace(' ', ''), valid_window=valid_window)
    except Exception as exc:
        logger.warning('[totp] verify failed: %s', exc)
        return False


def user_has_totp(user) -> bool:
    return bool(
        user
        and getattr(user, 'totp_enabled', False)
        and getattr(user, 'totp_secret', None)
    )
