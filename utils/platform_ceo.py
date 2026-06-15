"""TrainIQ platform CEO — full access bootstrap."""
from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime

logger = logging.getLogger(__name__)

PLATFORM_CEO_EMAIL = os.getenv("TRAINIQ_CEO_EMAIL", "thanuka.ellepola@gmail.com").lower().strip()
TRAINIQ_PLATFORM_OFFICE_KEY = os.getenv("TRAINIQ_PLATFORM_OFFICE_KEY", "TRAINIQ")


def _is_production() -> bool:
    env = (os.getenv("FLASK_ENV") or os.getenv("ENV") or "").lower()
    return env in ("production", "prod")


def _ceo_bootstrap_password() -> str | None:
    """Return CEO bootstrap password from env; never use a hardcoded production secret."""
    pw = (os.getenv("TRAINIQ_CEO_DEFAULT_PASSWORD") or "").strip()
    if pw:
        return pw
    if _is_production():
        return None
    # Dev-only: generate a one-time password and log it (no committed default).
    import secrets
    dev_pw = secrets.token_urlsafe(16)
    logger.warning(
        "TRAINIQ_CEO_DEFAULT_PASSWORD not set — generated dev password for %s: %s",
        PLATFORM_CEO_EMAIL,
        dev_pw,
    )
    return dev_pw


def is_platform_ceo(user=None) -> bool:
    from flask_login import current_user

    user = user or current_user
    if not user or not getattr(user, "is_authenticated", False):
        return False
    email = (getattr(user, "employee_email", "") or "").lower().strip()
    if email == PLATFORM_CEO_EMAIL:
        return True
    if getattr(user, "is_platform_staff", False) and (getattr(user, "platform_staff_role", "") or "").lower() == "ceo":
        return True
    return False


def ensure_platform_ceo():
    """Ensure CEO account and TrainIQ platform tenant exist."""
    from extensions import db
    from models import Tenant, User, Role
    from utils.tenant_seeds import seed_tenant_catalog
    from utils.mongo_tenant import provision_tenant_mongo

    try:
        tenant = Tenant.query.filter_by(office_key=TRAINIQ_PLATFORM_OFFICE_KEY).first()
        if not tenant:
            tenant = Tenant(
                name="TrainIQ Platform",
                allowed_domain="trainiq.com",
                office_key=TRAINIQ_PLATFORM_OFFICE_KEY,
                plan="enterprise",
                status="active",
                max_users=9999,
                max_storage_mb=102400,
            )
            db.session.add(tenant)
            db.session.flush()
            try:
                seed_tenant_catalog(tenant.id)
            except Exception as seed_exc:
                db.session.rollback()
                tenant = Tenant.query.filter_by(office_key=TRAINIQ_PLATFORM_OFFICE_KEY).first()
                if not tenant:
                    raise seed_exc
                logger.warning("Catalog seed skipped for platform tenant: %s", seed_exc)
            logger.info("Created TrainIQ Platform tenant id=%s", tenant.id)

        user = User.query.filter(db.func.lower(User.employee_email) == PLATFORM_CEO_EMAIL).first()
        if not user:
            bootstrap_pw = _ceo_bootstrap_password()
            if not bootstrap_pw:
                logger.error(
                    "TRAINIQ_CEO_DEFAULT_PASSWORD must be set in production to bootstrap CEO account"
                )
                return
            user = User(
                first_name="Thanuka",
                last_name="Ellepola",
                employee_email=PLATFORM_CEO_EMAIL,
                employee_id=f"CEO-{uuid.uuid4().hex[:6].upper()}",
                join_date=datetime.utcnow().date(),
                is_verified=True,
                is_super_admin=True,
                tenant_id=tenant.id,
                current_level=1,
            )
            user.is_platform_staff = True
            user.platform_staff_role = "ceo"
            user.set_password(bootstrap_pw)
            db.session.add(user)
            logger.info("Created platform CEO user %s", PLATFORM_CEO_EMAIL)
        else:
            user.is_super_admin = True
            user.is_verified = True
            user.is_platform_staff = True
            user.platform_staff_role = "ceo"
            if user.tenant_id != tenant.id:
                logger.warning(
                    "Reassigning platform CEO %s from tenant %s → platform tenant %s",
                    PLATFORM_CEO_EMAIL,
                    user.tenant_id,
                    tenant.id,
                )
                user.tenant_id = tenant.id
            elif not user.tenant_id:
                user.tenant_id = tenant.id

        for role_name in ("admin", "super_admin"):
            role = Role.query.filter_by(name=role_name).first()
            if role and role not in user.roles:
                user.roles.append(role)

        db.session.commit()
        provision_tenant_mongo(tenant.id)
        logger.info("Platform CEO bootstrap complete.")
    except Exception as exc:
        db.session.rollback()
        logger.error("Platform CEO bootstrap failed: %s", exc)
