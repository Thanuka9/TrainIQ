"""Unified access helpers — prefer current_user over session flags."""
from __future__ import annotations

from flask_login import current_user

from utils.admin_permissions import user_has_permission


def effective_is_super_admin(user=None) -> bool:
    """True when user is org super admin or TrainIQ staff in support mode."""
    from flask import has_request_context, session
    from utils.tenant_utils import is_trainiq_staff

    user = user or current_user
    if not user or not getattr(user, "is_authenticated", False):
        return False
    if getattr(user, "is_super_admin", False):
        return True
    if not has_request_context():
        return False
    return bool(session.get("platform_support") and is_trainiq_staff(user))


def can_upload_study_materials(user=None) -> bool:
    user = user or current_user
    if not user or not getattr(user, "is_authenticated", False):
        return False
    if effective_is_super_admin(user):
        return True
    if user_has_permission(user, "courses.manage"):
        return True
    # Legacy designation gate (content creators)
    return getattr(user, "designation_id", None) in (12,)


def user_role_label(user=None) -> str:
    user = user or current_user
    if not user or not getattr(user, "is_authenticated", False):
        return "member"
    if effective_is_super_admin(user):
        return "super_admin"
    if user.roles:
        return user.roles[0].name
    return "member"
