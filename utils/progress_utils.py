# utils/progress_utils.py
from utils.exam_grading import DEFAULT_PASSING_SCORE, get_passing_score
from models import Exam, LevelArea, StudyMaterial, UserProgress, UserScore
from extensions import db


# ---------------------------------------------------------------------
# 1. Study‑completion helper
# ---------------------------------------------------------------------
def has_finished_study(user_id: int, level_id: int, area_id: int) -> bool:
    """
    True ⇢ the user has completed *every* study‑material whose category
    belongs to this (level_id, area_id) pair.
    """
    # 1) Which category IDs map to this level + area?
    cat_rows = (
        db.session.query(LevelArea.category_id)
        .filter_by(level_id=level_id, area_id=area_id)
        .all()
    )
    category_ids = [cid for (cid,) in cat_rows]

    # If no mapping → no study materials required for this area
    if not category_ids:
        return True

    # 2) All StudyMaterial IDs in those categories + level
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
        return True

    # 3) Every required material must have a completed progress row
    completed = (
        db.session.query(UserProgress.study_material_id)
        .filter(
            UserProgress.user_id == user_id,
            UserProgress.study_material_id.in_(material_ids),
            db.or_(
                UserProgress.completed.is_(True),
                UserProgress.progress_percentage >= 100,
            ),
        )
        .distinct()
        .count()
    )
    return completed >= len(material_ids)


# ---------------------------------------------------------------------
# 2. Exam‑pass helper
# ---------------------------------------------------------------------
def has_passed_exam(user_id: int, level_id: int, area_id: int) -> bool:
    """
    True ⇢ the user's **best recorded score** for this area & level meets the exam passing threshold.
    (Change `.order_by(UserScore.score.desc())` to
     `.order_by(UserScore.created_at.desc())` if you prefer *latest attempt wins*.)
    """
    # utils/progress_utils.py       (keep everything else the same)

    best_attempt = (
        UserScore.query
        .filter_by(user_id=user_id, level_id=level_id, area_id=area_id)
        .order_by(UserScore.score.desc())
        .first()
    )

    return bool(best_attempt and best_attempt.score >= (
        get_passing_score(Exam.query.get(best_attempt.exam_id))
        if best_attempt.exam_id and Exam.query.get(best_attempt.exam_id)
        else DEFAULT_PASSING_SCORE
    ))


# ---------------------------------------------------------------------
# 3. Level‑completion helper
# ---------------------------------------------------------------------
def is_level_done(user, level_id: int) -> bool:
    """
    A level is complete when, for **every** required area,
      • study materials are 100 % read  AND
      • exam score meets the passing threshold for that area
    …unless the user’s designation allows skipping that specific exam.
    """
    for la in LevelArea.query.filter_by(level_id=level_id):
        # Skip only if (a) an exam exists for the area AND (b) user may skip it
        if la.required_exam and user.can_skip_exam(la.required_exam):
            continue

        if not (
            has_finished_study(user.id, level_id, la.area_id)
            and has_passed_exam(user.id, level_id, la.area_id)
        ):
            return False
    return True
