"""Secure GridFS file access — resolve study material ownership by file ObjectId."""
from __future__ import annotations

import logging

from flask import abort
from flask_login import current_user
from sqlalchemy import cast, Text

logger = logging.getLogger(__name__)


def find_material_for_file_id(file_id: str):
    """Return StudyMaterial that owns this GridFS file id, or None."""
    from models import StudyMaterial
    from sqlalchemy import or_

    if not file_id:
        return None
    fid = str(file_id).strip()
    needle = f"{fid}|"
    assets_text = cast(StudyMaterial.media_assets, Text)
    return (
        StudyMaterial.query.filter(
            or_(
                cast(StudyMaterial.files, Text).contains(needle),
                assets_text.contains(f'"mongo_id": "{fid}"'),
                assets_text.contains(f'"id": "{fid}"'),
            )
        ).first()
    )


def require_material_file_access(file_id: str):
    """
    Require authenticated user with tenant access to the material owning file_id.
    Returns (material, grid_file) — caller streams grid_file.
    """
    from utils.mongo_tenant import open_grid_file
    from utils.tenant_utils import assert_tenant_access

    if not current_user.is_authenticated:
        abort(401)

    material = find_material_for_file_id(file_id)
    if not material:
        logger.warning("GridFS access denied — no material for file_id=%s user=%s", file_id, current_user.id)
        abort(404)

    assert_tenant_access(material)

    if not material.is_accessible(current_user):
        abort(403)

    try:
        grid_file, _ = open_grid_file(file_id, material.tenant_id)
    except Exception:
        abort(404)

    meta_tid = (grid_file.metadata or {}).get("tenant_id")
    if meta_tid is not None and material.tenant_id is not None and int(meta_tid) != int(material.tenant_id):
        logger.warning("GridFS tenant mismatch file_id=%s", file_id)
        abort(403)

    return material, grid_file
