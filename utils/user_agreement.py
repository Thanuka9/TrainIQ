"""TrainIQ Platform User Agreement — version tracking and acceptance."""
from __future__ import annotations

import hashlib
import logging
import os
from datetime import datetime

from flask import request

logger = logging.getLogger(__name__)

# Bump version when legal text changes materially — users must re-accept.
CURRENT_AGREEMENT_VERSION = os.getenv("TRAINIQ_AGREEMENT_VERSION", "2026.4")
EFFECTIVE_DATE = os.getenv("TRAINIQ_AGREEMENT_EFFECTIVE_DATE", "June 15, 2026")
LEGAL_ENTITY = os.getenv("TRAINIQ_LEGAL_ENTITY", "Veyra Labs")
OWNER_NAME = os.getenv("TRAINIQ_OWNER_NAME", "Thanuka Ellepola")
OWNER_ORGANIZATION = os.getenv("TRAINIQ_OWNER_ORGANIZATION", "Veyra Labs")
OWNER_URL = os.getenv("TRAINIQ_OWNER_URL", "https://thanukaellepola.careers/en")
GOVERNING_LAW = os.getenv(
    "TRAINIQ_GOVERNING_LAW",
    "the State of Delaware, United States of America",
)
LEGAL_EMAIL = os.getenv("TRAINIQ_LEGAL_EMAIL", "legal@veyralabs.com")
SUPPORT_EMAIL = os.getenv("TRAINIQ_SUPPORT_EMAIL", "support@trainiq.com")
WEBSITE_URL = os.getenv("TRAINIQ_WEBSITE_URL", "https://trainiq.com")
TRIAL_DAYS = int(os.getenv("TRAINIQ_TRIAL_DAYS", "30"))


def agreement_document_hash() -> str:
    payload = "|".join([
        CURRENT_AGREEMENT_VERSION,
        EFFECTIVE_DATE,
        LEGAL_ENTITY,
        OWNER_NAME,
        OWNER_ORGANIZATION,
        OWNER_URL,
        "platform-user-agreement-v5-billing",
    ])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def user_has_accepted_agreement(user) -> bool:
    if not user:
        return False
    version = getattr(user, "user_agreement_version", None)
    return version == CURRENT_AGREEMENT_VERSION


def user_needs_agreement(user) -> bool:
    return not user_has_accepted_agreement(user)


AGREEMENT_EXEMPT_ENDPOINTS = frozenset({
    "static",
    "ping",
    "auth_routes.login",
    "auth_routes.logout",
    "auth_routes.register",
    "auth_routes.verify_email",
    "auth_routes.resend_verification",
    "auth_routes.forgot_password",
    "auth_routes.reset_password",
    "auth_routes.accept_staff_invite",
    "general_routes.user_agreement_accept",
    "general_routes.user_agreement_view",
    "general_routes.privacy_policy",
    "general_routes.privacy_policy_agreement",
    "general_routes.home",
    "root",
})


AGREEMENT_EXEMPT_PATH_PREFIXES = (
    "/static/",
    "/auth/",
)


def is_agreement_exempt_endpoint(endpoint: str | None, path: str = "") -> bool:
    if endpoint in AGREEMENT_EXEMPT_ENDPOINTS:
        return True
    if path.startswith(AGREEMENT_EXEMPT_PATH_PREFIXES):
        return True
    if path in ("/", "/home", "/pricing", "/privacy-policy", "/help", "/user-agreement"):
        return True
    return False


def record_agreement_acceptance(user, *, ip_address: str | None = None, user_agent: str | None = None):
    """Persist acceptance on user profile and append immutable audit row."""
    from extensions import db
    from models import UserAgreementAcceptance

    now = datetime.utcnow()
    user.user_agreement_version = CURRENT_AGREEMENT_VERSION
    user.user_agreement_at = now
    user.privacy_agreed = True
    user.privacy_agreed_at = now

    acceptance = UserAgreementAcceptance(
        user_id=user.id,
        agreement_version=CURRENT_AGREEMENT_VERSION,
        document_hash=agreement_document_hash(),
        accepted_at=now,
        ip_address=(ip_address or "")[:45] or None,
        user_agent=(user_agent or "")[:500] or None,
    )
    db.session.add(acceptance)
    db.session.commit()

    try:
        from audit import log_event
        log_event(
            "USER_AGREEMENT_ACCEPTED",
            user=user,
            agreement_version=CURRENT_AGREEMENT_VERSION,
            document_hash=agreement_document_hash(),
            ip_address=ip_address,
        )
    except Exception as exc:
        logger.debug("Agreement audit log skipped: %s", exc)

    return acceptance


def agreement_context() -> dict:
    return {
        "agreement_version": CURRENT_AGREEMENT_VERSION,
        "agreement_effective_date": EFFECTIVE_DATE,
        "legal_entity": LEGAL_ENTITY,
        "owner_name": OWNER_NAME,
        "owner_organization": OWNER_ORGANIZATION,
        "owner_url": OWNER_URL,
        "governing_law": GOVERNING_LAW,
        "legal_email": LEGAL_EMAIL,
        "support_email": SUPPORT_EMAIL,
        "website_url": WEBSITE_URL,
        "document_hash": agreement_document_hash(),
        "trial_days": TRIAL_DAYS,
    }
