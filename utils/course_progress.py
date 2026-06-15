"""Unified course progress from PDF pages and per-asset watch/view state."""
from __future__ import annotations

from utils.course_assets import assets_from_study_material


def recalc_user_progress(study_material, prog) -> None:
    """
    Recompute progress_percentage and completed from asset_progress JSON
    and legacy pages_visited (PDF multi-page courses).
    """
    assets = assets_from_study_material(study_material)
    ap = dict(prog.asset_progress or {})

    if not assets:
        total = max(study_material.total_pages or 1, 1)
        raw = int((prog.pages_visited or 0) / total * 100)
        prog.progress_percentage = min(raw, 100)
    else:
        percents = [int(ap.get(str(a.get("id")), 0)) for a in assets]
        if percents:
            prog.progress_percentage = min(100, int(sum(percents) / len(percents)))
        else:
            prog.progress_percentage = 0

    if prog.progress_percentage >= 100:
        prog.progress_percentage = 100
        prog.completed = True
    else:
        prog.completed = False
