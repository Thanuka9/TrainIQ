"""Platform staff role definitions and permission checks."""
from __future__ import annotations

from utils.platform_ceo import is_platform_ceo

# Permission codes used on platform routes and templates.
PERMISSION_LABELS = {
    "dashboard.view": "Command Center overview",
    "support.view": "Support ticket queue",
    "users.view": "Cross-tenant user search",
    "users.actions": "User actions (unlock level, resend verification, force reset)",
    "tenants.view": "Organization list and detail",
    "tenants.enter": "Enter tenant support mode",
    "tenants.manage": "Suspend, activate, and update tenant plans",
    "activity.view": "Platform activity feed",
    "activity.export": "Export activity CSV",
    "security.view": "Security audit feed",
    "revenue.view": "Revenue analytics",
    "exports.data": "Export tenants and users CSV",
    "staff.view": "Staff hub page",
    "staff.manage": "Invite, deactivate, and change staff roles (CEO only)",
    "operations.view": "Platform operations console (CEO only)",
}

ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    "support": frozenset({
        "dashboard.view",
        "support.view",
        "users.view",
        "users.actions",
        "tenants.view",
        "tenants.enter",
        "staff.view",
    }),
    "ops": frozenset({
        "dashboard.view",
        "support.view",
        "users.view",
        "users.actions",
        "tenants.view",
        "tenants.enter",
        "activity.view",
        "activity.export",
        "staff.view",
    }),
    "admin": frozenset({
        "dashboard.view",
        "support.view",
        "users.view",
        "users.actions",
        "tenants.view",
        "tenants.enter",
        "tenants.manage",
        "activity.view",
        "activity.export",
        "security.view",
        "revenue.view",
        "exports.data",
        "staff.view",
    }),
}

ROLE_DESCRIPTIONS = {
    "support": "Front-line customer support — tickets, user lookup, and read-only tenant access.",
    "ops": "Operations — support plus activity monitoring and audit exports.",
    "admin": "Platform admin — full tenant management, security, revenue, and data exports.",
    "ceo": "Platform CEO — all admin powers plus staff invitations and role management.",
}

SUBNAV_PERMISSIONS = {
    "dashboard": "dashboard.view",
    "tenants": "tenants.view",
    "users": "users.view",
    "staff": "staff.view",
    "support": "support.view",
    "security": "security.view",
    "activity": "activity.view",
    "revenue": "revenue.view",
    "operations": "operations.view",
}


def effective_staff_role(user) -> str | None:
    if not user or not getattr(user, "is_platform_staff", False):
        if user and is_platform_ceo(user):
            return "ceo"
        return None
    if is_platform_ceo(user):
        return "ceo"
    return (getattr(user, "platform_staff_role", None) or "support").lower()


def staff_has_permission(user, permission: str) -> bool:
    if not user or not getattr(user, "is_authenticated", True):
        return False
    if is_platform_ceo(user):
        return True
    if not getattr(user, "is_platform_staff", False):
        return False
    role = effective_staff_role(user)
    perms = ROLE_PERMISSIONS.get(role or "", frozenset())
    return permission in perms


def get_role_catalog() -> list[dict]:
    """Role metadata for CEO staff management UI."""
    rows = []
    for role_id in ("support", "ops", "admin"):
        perms = sorted(ROLE_PERMISSIONS.get(role_id, frozenset()))
        rows.append({
            "id": role_id,
            "label": role_id.title(),
            "description": ROLE_DESCRIPTIONS.get(role_id, ""),
            "permissions": [
                {"code": p, "label": PERMISSION_LABELS.get(p, p)}
                for p in perms
            ],
        })
    rows.append({
        "id": "ceo",
        "label": "CEO",
        "description": ROLE_DESCRIPTIONS["ceo"],
        "permissions": [
            {"code": p, "label": PERMISSION_LABELS.get(p, p)}
            for p in sorted(PERMISSION_LABELS.keys())
        ],
    })
    return rows


def visible_platform_tabs(user) -> set[str]:
    """Subnav tab keys the user may see."""
    return {key for key, perm in SUBNAV_PERMISSIONS.items() if staff_has_permission(user, perm)}
