"""Shared level unlock and course access helpers."""
from __future__ import annotations

import logging

from extensions import db
from models import Area, Level, LevelArea, StudyMaterial, User, UserLevelProgress, UserProgress
from utils.progress_utils import has_finished_study, has_passed_exam


def material_progression_level(study_material) -> int:
    """Curriculum level number used for sequential unlock (not designation gate)."""
    if getattr(study_material, "level", None) and study_material.level.level_number:
        return int(study_material.level.level_number)
    return int(study_material.minimum_level or 1)


def can_access_exam_level(user, exam) -> bool:
    """True when the user's progression or designation allows this exam's level."""
    if not user or not getattr(exam, "level", None):
        return True

    level_number = int(exam.level.level_number or 1)
    if level_number <= 1:
        return True
    if user.designation and user.designation.can_skip_level(level_number):
        return True
    return int(user.get_current_level() or 1) >= level_number


def can_access_study_material(user, study_material) -> bool:
    """
    Return True when the user may access a study material.

    Two independent gates must pass:
      1) Designation gate — ``minimum_level`` (designation starting level threshold)
      2) Progression gate — curriculum ``level.level_number`` (sequential unlock)
    """
    if not user:
        return False

    min_desig = int(study_material.minimum_level or 1)
    prog_level = material_progression_level(study_material)
    user_level = int(user.get_current_level() or 1)

    desig_ok = (
        min_desig <= 1
        or (
            user.designation
            and int(user.designation.starting_level or 0) >= min_desig
        )
    )
    if not desig_ok:
        return False

    return (
        prog_level <= 1
        or (user.designation and user.designation.can_skip_level(prog_level))
        or user_level >= prog_level
    )


def can_access_level_number(user, level_number: int) -> bool:
    """
    Return True when the user may access content at ``level_number``.

    Level 1 is open to everyone. Higher levels require either:
      • current progression, designation skip, or completed previous level.
    """
    if not user:
        return False

    try:
        required = int(level_number or 1)
    except (TypeError, ValueError):
        required = 1

    if required <= 1:
        return True

    user_level = int(user.get_current_level() or 1)
    if user_level >= required:
        return True

    if user.designation and user.designation.can_skip_level(required):
        return True

    from utils.tenant_utils import tenant_levels_query

    prev = tenant_levels_query(user).filter_by(level_number=required - 1).first()
    if not prev:
        return True

    return check_level_completion(user.id, prev.id)


def check_level_completion(user_id: int, level_db_id: int) -> bool:
    """
    True when the user completed every LevelArea requirement for ``level_db_id``:
      • 100% study completion per area
      • required exams passed (unless skipped by designation)
    """
    try:
        user = User.query.get(user_id)
        if not user:
            return False

        level_areas = LevelArea.query.filter_by(level_id=level_db_id).all()
        if not level_areas:
            return True

        for la in level_areas:
            if not has_finished_study(user_id, level_db_id, la.area_id):
                return False

            if not la.required_exam_id:
                continue

            if user.can_skip_exam(la.required_exam):
                continue

            prog = UserLevelProgress.query.filter_by(
                user_id=user_id,
                level_id=level_db_id,
                area_id=la.area_id,
                status="completed",
            ).first()
            if prog:
                continue

            if not has_passed_exam(user_id, level_db_id, la.area_id):
                return False

        return True

    except Exception as exc:
        logging.warning(
            "Level completion check failed for user %s, level %s: %s",
            user_id,
            level_db_id,
            exc,
        )
        return False


def get_level_journey(user) -> list[dict]:
    """Learner-facing level progression snapshot for dashboard widget."""
    if not user:
        return []

    from utils.tenant_utils import tenant_levels_query

    levels = tenant_levels_query(user).order_by(Level.level_number).all()
    current = int(user.get_current_level() or 1)
    journey = []
    for lvl in levels:
        num = int(lvl.level_number or 1)
        if check_level_completion(user.id, lvl.id):
            status = "completed"
        elif num < current:
            status = "completed"
        elif num == current:
            status = "current"
        elif num == current + 1:
            status = "next"
        else:
            status = "locked"
        journey.append({
            "level_number": num,
            "level_id": lvl.id,
            "status": status,
        })
    return journey


def _area_study_percent(user_id: int, level_id: int, area_id: int) -> int:
    """Average study completion % for materials mapped to a level area."""
    category_ids = [
        cid
        for (cid,) in db.session.query(LevelArea.category_id)
        .filter_by(level_id=level_id, area_id=area_id)
        .all()
    ]
    if not category_ids:
        return 100

    material_ids = [
        mid
        for (mid,) in db.session.query(StudyMaterial.id)
        .filter(
            StudyMaterial.level_id == level_id,
            StudyMaterial.category_id.in_(category_ids),
        )
        .all()
    ]
    if not material_ids:
        return 100

    progress_rows = {
        row.study_material_id: row
        for row in UserProgress.query.filter(
            UserProgress.user_id == user_id,
            UserProgress.study_material_id.in_(material_ids),
        ).all()
    }

    total = 0.0
    for material_id in material_ids:
        prog = progress_rows.get(material_id)
        if not prog:
            continue
        pct = float(prog.progress_percentage or 0)
        if prog.completed or pct >= 100:
            pct = 100.0
        total += min(100.0, pct)
    return int(round(total / len(material_ids)))


def get_area_progress_summary(user) -> list[dict]:
    """For the user's current level, list areas with study % and exam pass status."""
    if not user:
        return []

    from utils.tenant_utils import tenant_levels_query

    current_number = int(user.get_current_level() or 1)
    level = tenant_levels_query(user).filter_by(level_number=current_number).first()
    if not level:
        return []

    level_areas = LevelArea.query.filter_by(level_id=level.id).all()
    if not level_areas:
        return []

    seen_areas: dict[int, LevelArea] = {}
    for la in level_areas:
        seen_areas.setdefault(la.area_id, la)

    summary = []
    for area_id, la in sorted(seen_areas.items(), key=lambda item: item[0]):
        area = la.area or Area.query.get(area_id)
        study_percent = _area_study_percent(user.id, level.id, area_id)
        exam_required = any(
            row.required_exam_id
            for row in level_areas
            if row.area_id == area_id
        )

        exam_passed = None
        if exam_required:
            required_rows = [row for row in level_areas if row.area_id == area_id and row.required_exam_id]
            skipped = any(
                row.required_exam and user.can_skip_exam(row.required_exam)
                for row in required_rows
            )
            if skipped:
                exam_passed = "skipped"
            else:
                exam_passed = has_passed_exam(user.id, level.id, area_id)

        summary.append(
            {
                "area_id": area_id,
                "area_name": area.name if area else f"Area {area_id}",
                "study_percent": study_percent,
                "study_complete": study_percent >= 100,
                "exam_required": exam_required,
                "exam_passed": exam_passed,
            }
        )
    return summary


def advance_user_level_after_completion(user_id: int, level_db_id: int):
    """
    Bump ``user.current_level`` to the next ``level_number`` when ``level_db_id``
    is fully complete. Returns the unlocked level number, or None.
    """
    from utils.tenant_utils import tenant_levels_query

    user = User.query.get(user_id)
    level = Level.query.get(level_db_id)
    if not user or not level:
        return None

    if not check_level_completion(user_id, level_db_id):
        return None

    next_level = tenant_levels_query().filter_by(
        level_number=level.level_number + 1
    ).first()
    if not next_level:
        return None

    if int(user.get_current_level() or 1) < next_level.level_number:
        user.current_level = next_level.level_number
        db.session.commit()

        try:
            from flask import url_for

            from utils.notifications import create_notification

            create_notification(
                user_id,
                f"Level {next_level.level_number} unlocked!",
                (
                    f"Congratulations! You completed Level {level.level_number} "
                    f"and unlocked Level {next_level.level_number}."
                ),
                category="success",
                link_url=url_for("general_routes.dashboard"),
                icon="layer-group",
                dedupe_key=f"level_unlock_{user_id}_{next_level.level_number}",
            )
        except Exception as exc:
            logging.warning("Level unlock notification failed for user %s: %s", user_id, exc)

        return next_level.level_number

    return None
