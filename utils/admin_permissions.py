"""
Flexible admin permission resolution for TrainIQ organizations.

Layers (highest wins last):
  1. Super Admin flag → full org access (except TrainIQ platform routes)
  2. Role templates (admin, hr, manager, …)
  3. User overrides: grants add access, denies revoke access

Admins assign granular access via Users → Access without making someone Super Admin.
"""
from __future__ import annotations

from typing import Any, Dict, FrozenSet, Iterable, List, Optional, Set, Tuple

# ── Permission catalog (code → label, sidebar group) ────────────────────────
PERMISSION_GROUPS: Tuple[Tuple[str, str], ...] = (
    ("overview", "Overview"),
    ("management", "Management"),
    ("insights", "Data & Insights"),
    ("operations", "Operations"),
    ("organization", "Organization"),
)

PERMISSIONS: Dict[str, Tuple[str, str]] = {
    "dashboard": ("Admin dashboard", "overview"),
    "users.manage": ("Users — view & manage", "management"),
    "users.permissions": ("Manage user access", "management"),
    "courses.manage": ("Courses", "management"),
    "exams.manage": ("Exams", "management"),
    "roles.manage": ("Roles", "management"),
    "clients.manage": ("User–Clients", "management"),
    "level_areas.manage": ("Level areas", "management"),
    "analytics.view": ("Analytics", "insights"),
    "reports.view": ("Reports", "insights"),
    "incorrect.view": ("Incorrect answers", "insights"),
    "proctor.view": ("ProctorIQ review", "insights"),
    "audit.view": ("Audit logs", "insights"),
    "exam_requests.manage": ("Exam requests", "operations"),
    "announcements.manage": ("Announcements", "operations"),
    "support.manage": ("Support tickets", "operations"),
    "seeds.manage": ("Seed data", "operations"),
    "org.billing": ("Billing", "organization"),
    "org.settings": ("Organization settings", "organization"),
}

ALL_ORG_PERMISSIONS: FrozenSet[str] = frozenset(PERMISSIONS.keys())

# Only Super Admins may grant these to others
SENSITIVE_PERMISSIONS: FrozenSet[str] = frozenset({
    "users.permissions",
    "org.billing",
    "org.settings",
    "seeds.manage",
})

# ── Role templates (additive base layer) ────────────────────────────────────
ROLE_TEMPLATES: Dict[str, FrozenSet[str]] = {
    "admin": ALL_ORG_PERMISSIONS - SENSITIVE_PERMISSIONS - frozenset({"users.permissions"}),
    "manager": frozenset({
        "dashboard", "users.manage", "analytics.view", "reports.view",
        "exam_requests.manage", "support.manage", "incorrect.view",
    }),
    "hr": frozenset({
        "dashboard", "users.manage", "roles.manage", "clients.manage",
    }),
    "finance": frozenset({
        "dashboard", "reports.view", "org.billing",
    }),
    "member": frozenset(),
    "super_admin": frozenset(),  # handled by is_super_admin flag
}

# ── UI presets (quick-assign bundles) ───────────────────────────────────────
PERMISSION_PRESETS: Dict[str, Tuple[str, FrozenSet[str]]] = {
    "custom": ("Custom (manual selection)", frozenset()),
    "content_manager": (
        "Content manager",
        frozenset({"dashboard", "courses.manage", "exams.manage", "level_areas.manage"}),
    ),
    "people_hr": (
        "People & HR",
        frozenset({"dashboard", "users.manage", "roles.manage", "clients.manage"}),
    ),
    "analyst": (
        "Analyst / QA",
        frozenset({
            "dashboard", "analytics.view", "reports.view", "incorrect.view",
            "proctor.view", "audit.view",
        }),
    ),
    "support_lead": (
        "Support & exams",
        frozenset({"dashboard", "support.manage", "exam_requests.manage"}),
    ),
    "communications": (
        "Communications",
        frozenset({"dashboard", "announcements.manage"}),
    ),
    "dept_admin": (
        "Department admin",
        frozenset(ALL_ORG_PERMISSIONS - SENSITIVE_PERMISSIONS),
    ),
}

# ── Route → permission (None = Super Admin only) ────────────────────────────
ROUTE_PERMISSIONS: Dict[str, Optional[str]] = {
    "admin_dashboard": "dashboard",
    "tenant_settings": None,
    "ai_generate_exam_questions": "exams.manage",
    "ai_preview_exam_questions": "exams.manage",
    "delete_course": "courses.manage",
    "set_restrictions": "courses.manage",
    "edit_course": "courses.manage",
    "delete_exam": "exams.manage",
    "edit_exam": "exams.manage",
    "delete_question": "exams.manage",
    "edit_exam_page": "exams.manage",
    "correct_question_ai": "exams.manage",
    "generate_exam_questions_ai": "exams.manage",
    "update_question": "exams.manage",
    "generate_reports": "reports.view",
    "view_special_exam_record": "analytics.view",
    "view_users": "users.manage",
    "send_user_invite": "users.manage",
    "set_user_super_admin": None,
    "change_designation": "users.manage",
    "change_user_departments": "users.manage",
    "view_courses": "courses.manage",
    "creatoriq_generate_outline_start": "courses.manage",
    "creatoriq_generate_outline": "courses.manage",
    "proctoriq_review": "proctor.view",
    "view_exams": "exams.manage",
    "view_analytics": "analytics.view",
    "analytics_ai_insights": "analytics.view",
    "analytics_export_pdf": "analytics.view",
    "analytics_user_list": "analytics.view",
    "analytics_user_detail": "analytics.view",
    "deactivate_user": "users.manage",
    "activate_user": "users.manage",
    "delete_user": "users.manage",
    "view_roles": "roles.manage",
    "assign_role": "roles.manage",
    "view_audit_logs": "audit.view",
    "bulk_user_action": "users.manage",
    "manage_exam_requests": "exam_requests.manage",
    "incorrect_summary": "incorrect.view",
    "view_incorrect_answers": "incorrect.view",
    "clear_incorrect_answers": "incorrect.view",
    "manage_level_areas": "level_areas.manage",
    "create_level_area": "level_areas.manage",
    "edit_level_area": "level_areas.manage",
    "delete_level_area": "level_areas.manage",
    "manage_user_clients": "clients.manage",
    "add_user_client": "clients.manage",
    "edit_user_client": "clients.manage",
    "delete_user_client": "clients.manage",
    "manage_seeds": "seeds.manage",
    "add_role": "seeds.manage",
    "edit_role": "seeds.manage",
    "delete_role": "seeds.manage",
    "add_designation": "seeds.manage",
    "edit_designation": "seeds.manage",
    "delete_designation": "seeds.manage",
    "add_department": "seeds.manage",
    "edit_department": "seeds.manage",
    "delete_department": "seeds.manage",
    "add_client": "seeds.manage",
    "edit_client": "seeds.manage",
    "delete_client": "seeds.manage",
    "add_level": "seeds.manage",
    "edit_level": "seeds.manage",
    "delete_level": "seeds.manage",
    "add_area": "seeds.manage",
    "edit_area": "seeds.manage",
    "delete_area": "seeds.manage",
    "add_category": "seeds.manage",
    "edit_category": "seeds.manage",
    "delete_category": "seeds.manage",
    "manage_announcements": "announcements.manage",
    "create_announcement": "announcements.manage",
    "update_announcement": "announcements.manage",
    "delete_announcement": "announcements.manage",
    "admin_list_tickets": "support.manage",
    "admin_view_ticket": "support.manage",
    "manage_user_permissions": "users.permissions",
    "update_user_permissions": "users.permissions",
    "billing_home": "org.billing",
    "billing_upgrade": "org.billing",
}


def _normalize_overrides(raw: Any) -> Dict[str, List[str]]:
    if not raw or not isinstance(raw, dict):
        return {"grants": [], "denies": [], "preset": "custom"}
    grants = [p for p in (raw.get("grants") or []) if p in PERMISSIONS]
    denies = [p for p in (raw.get("denies") or []) if p in PERMISSIONS]
    preset = raw.get("preset") or "custom"
    if preset not in PERMISSION_PRESETS:
        preset = "custom"
    return {"grants": grants, "denies": denies, "preset": preset}


def resolve_role_permissions(user) -> Set[str]:
    """Permissions inherited from assigned roles only."""
    perms: Set[str] = set()
    for role in getattr(user, "roles", []) or []:
        perms |= set(ROLE_TEMPLATES.get(role.name, ()))
    return perms


def resolve_permissions(user) -> Set[str]:
    """Effective org-level admin permissions for a user."""
    if not user:
        return set()
    if getattr(user, "is_super_admin", False):
        return set(ALL_ORG_PERMISSIONS)

    perms = set(resolve_role_permissions(user))
    overrides = _normalize_overrides(getattr(user, "admin_permissions", None))
    perms |= set(overrides["grants"])
    perms -= set(overrides["denies"])
    return perms


def permission_breakdown(user) -> Dict[str, Any]:
    """Structured breakdown for the access editor UI."""
    if getattr(user, "is_super_admin", False):
        return {
            "role": set(ALL_ORG_PERMISSIONS),
            "grants": set(),
            "denies": set(),
            "effective": set(ALL_ORG_PERMISSIONS),
        }
    role = resolve_role_permissions(user)
    overrides = _normalize_overrides(getattr(user, "admin_permissions", None))
    grants = set(overrides["grants"])
    denies = set(overrides["denies"])
    effective = (role | grants) - denies
    return {"role": role, "grants": grants, "denies": denies, "effective": effective}


def user_can_manage_permissions(user) -> bool:
    return user_has_permission(user, "users.permissions")


def user_has_permission(user, permission_code: str) -> bool:
    if not user:
        return False
    if getattr(user, "is_super_admin", False):
        return permission_code in PERMISSIONS
    perms = resolve_permissions(user)
    if permission_code == "dashboard":
        return bool(perms)
    return permission_code in perms


def user_can_access_admin(user) -> bool:
    if not user:
        return False
    if getattr(user, "is_super_admin", False):
        return True
    if resolve_permissions(user):
        return True
    # Legacy: admin role (id 2) without explicit overrides still gets panel access
    return any(getattr(r, "id", None) == 2 for r in (getattr(user, "roles", []) or []))


def route_requires_super_admin(view_name: str) -> bool:
    return view_name in ROUTE_PERMISSIONS and ROUTE_PERMISSIONS[view_name] is None


def user_can_access_route(user, view_name: str, *, effective_super_admin: bool = False) -> bool:
    if effective_super_admin:
        return True
    if route_requires_super_admin(view_name):
        return bool(getattr(user, "is_super_admin", False))
    perm = ROUTE_PERMISSIONS.get(view_name)
    if perm:
        return user_has_permission(user, perm)
    return user_can_access_admin(user)


def permissions_for_template(user) -> Dict[str, bool]:
    """Map of permission code → granted (for Jinja checkboxes)."""
    effective = resolve_permissions(user)
    return {code: code in effective for code in PERMISSIONS}


def grouped_permissions(*, editable_only: bool = False) -> List[Tuple[str, str, List[Tuple[str, str]]]]:
    """Return [(group_id, group_label, [(code, label), ...]), ...] for UI."""
    buckets: Dict[str, List[Tuple[str, str]]] = {g[0]: [] for g in PERMISSION_GROUPS}
    for code, (label, group) in PERMISSIONS.items():
        if editable_only and code == "dashboard":
            continue
        buckets.setdefault(group, []).append((code, label))
    return [(gid, glabel, buckets.get(gid, [])) for gid, glabel in PERMISSION_GROUPS if buckets.get(gid)]


def filter_assignable_permissions(codes: Iterable[str], *, allow_sensitive: bool) -> List[str]:
    allowed = ALL_ORG_PERMISSIONS if allow_sensitive else (ALL_ORG_PERMISSIONS - SENSITIVE_PERMISSIONS)
    return sorted({c for c in codes if c in allowed})


def apply_preset_for_user(user, preset_key: str) -> dict:
    """Apply a named preset relative to the user's role base."""
    if preset_key == "custom":
        return _normalize_overrides(getattr(user, "admin_permissions", None))
    _, preset_perms = PERMISSION_PRESETS.get(preset_key, PERMISSION_PRESETS["custom"])
    data = compute_overrides_from_desired(user, preset_perms)
    data["preset"] = preset_key
    return data


def apply_preset_to_overrides(preset_key: str, existing: Optional[dict] = None) -> dict:
    """Legacy helper when user context is unavailable — stores grants as absolute preset."""
    if preset_key == "custom":
        return _normalize_overrides(existing)
    _, preset_perms = PERMISSION_PRESETS.get(preset_key, PERMISSION_PRESETS["custom"])
    return {"preset": preset_key, "grants": sorted(preset_perms), "denies": []}


def compute_overrides_from_desired(user, desired: Iterable[str]) -> dict:
    """Convert desired effective permissions into grant/deny overrides vs role base."""
    role_perms: Set[str] = set()
    for role in getattr(user, "roles", []) or []:
        role_perms |= set(ROLE_TEMPLATES.get(role.name, ()))
    desired_set = set(desired) & ALL_ORG_PERMISSIONS
    return {
        "preset": "custom",
        "grants": sorted(desired_set - role_perms),
        "denies": sorted(role_perms - desired_set),
    }


def sanitize_permission_payload(
    grants: Iterable[str],
    denies: Iterable[str],
    *,
    allow_sensitive: bool,
) -> dict:
    """Validate and strip permissions the editor is not allowed to assign."""
    allowed = ALL_ORG_PERMISSIONS if allow_sensitive else (ALL_ORG_PERMISSIONS - SENSITIVE_PERMISSIONS)
    g = sorted({p for p in grants if p in allowed})
    d = sorted({p for p in denies if p in allowed})
    return {"preset": "custom", "grants": g, "denies": d}


def permission_summary(user) -> str:
    """Short human-readable summary for user lists."""
    if getattr(user, "is_super_admin", False):
        return "Super Admin"
    perms = resolve_permissions(user) - {"dashboard"}
    if not perms:
        role_names = [r.name for r in (getattr(user, "roles", []) or [])]
        if role_names:
            return f"Role: {', '.join(role_names)}"
        return "Member"
    overrides = _normalize_overrides(getattr(user, "admin_permissions", None))
    preset = overrides.get("preset")
    if preset and preset != "custom" and preset in PERMISSION_PRESETS:
        return PERMISSION_PRESETS[preset][0]
    if len(perms) <= 3:
        return ", ".join(PERMISSIONS[p][0] for p in sorted(perms)[:3])
    return f"{len(perms)} admin areas"
