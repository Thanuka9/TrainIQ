"""Recommended next course for learners."""
from __future__ import annotations

from models import StudyMaterial, UserProgress
from utils.level_access import can_access_study_material, material_progression_level
from utils.tenant_utils import filter_by_user_tenant


def _material_complete(user_id: int, material_id: int) -> bool:
    prog = UserProgress.query.filter_by(
        user_id=user_id,
        study_material_id=material_id,
    ).first()
    if not prog:
        return False
    return bool(prog.completed or (prog.progress_percentage or 0) >= 100)


def get_recommended_next_course(user):
    """
    Return the first accessible, incomplete study material at the user's
    current curriculum level, or None when nothing matches.
    """
    if not user:
        return None

    current_level = int(user.get_current_level() or 1)
    materials = (
        filter_by_user_tenant(StudyMaterial.query, StudyMaterial)
        .order_by(StudyMaterial.id)
        .all()
    )

    for material in materials:
        if material_progression_level(material) != current_level:
            continue
        if not can_access_study_material(user, material):
            continue
        if _material_complete(user.id, material.id):
            continue
        return material

    return None
