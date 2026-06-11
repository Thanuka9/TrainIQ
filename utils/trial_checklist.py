"""In-app trial onboarding checklist — course, invites, exam."""
from __future__ import annotations

from typing import Any

INVITE_TARGET = 3


def get_trial_checklist(tenant) -> dict[str, Any] | None:
    """Progress widget data for trial Super Admins. None if not on trial."""
    if not tenant:
        return None
    if (getattr(tenant, "plan", "") or "").lower() != "trial":
        return None

    from utils.billing_plans import trial_days_remaining

    course_done = _has_course(tenant.id)
    invite_count = _team_member_count(tenant.id)
    invite_done = invite_count >= INVITE_TARGET
    exam_done = _has_exam_attempt(tenant.id)

    steps = [
        {
            "id": "course",
            "label": "Upload a course",
            "description": "Add study materials your team will learn from",
            "done": course_done,
            "url_name": "study_material_routes.upload_course",
            "icon": "fa-book",
        },
        {
            "id": "invite",
            "label": f"Invite {INVITE_TARGET} team members",
            "description": f"{invite_count}/{INVITE_TARGET} members added",
            "done": invite_done,
            "url_name": "admin_routes.view_users",
            "icon": "fa-user-plus",
            "progress": min(100, int((invite_count / INVITE_TARGET) * 100)),
        },
        {
            "id": "exam",
            "label": "Run a proctored exam",
            "description": "Create an exam and record at least one attempt",
            "done": exam_done,
            "url_name": "exams_routes.create_exam",
            "icon": "fa-shield-halved",
        },
    ]
    completed = sum(1 for s in steps if s["done"])
    return {
        "steps": steps,
        "completed": completed,
        "total": len(steps),
        "percent": int((completed / len(steps)) * 100),
        "all_done": completed == len(steps),
        "trial_days_left": trial_days_remaining(tenant),
    }


def _has_course(tenant_id: int) -> bool:
    from models import StudyMaterial
    return StudyMaterial.query.filter_by(tenant_id=tenant_id).count() > 0


def _team_member_count(tenant_id: int) -> int:
    from models import User
    return User.query.filter_by(tenant_id=tenant_id, is_super_admin=False).count()


def _has_exam_attempt(tenant_id: int) -> bool:
    from models import Exam, UserScore

    exam_ids = [e.id for e in Exam.query.filter_by(tenant_id=tenant_id).all()]
    if not exam_ids:
        return False
    return UserScore.query.filter(UserScore.exam_id.in_(exam_ids)).count() > 0
