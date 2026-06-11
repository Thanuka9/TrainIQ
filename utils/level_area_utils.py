"""Validate LevelArea rows belong to a single tenant catalog."""
from __future__ import annotations

from flask import flash


def catalog_ids_same_tenant(level_id, category_id, area_id, tenant_id) -> bool:
    from models import Area, Category, Level

    level = Level.query.get(level_id)
    category = Category.query.get(category_id)
    area = Area.query.get(area_id)
    if not level or not category or not area:
        return False
    ids = {level.tenant_id, category.tenant_id, area.tenant_id}
    if tenant_id is not None:
        return ids == {tenant_id}
    return len(ids) <= 1 and None not in ids


def validate_level_area_refs(level_id, category_id, area_id, tenant_id=None):
    ok = catalog_ids_same_tenant(level_id, category_id, area_id, tenant_id)
    if not ok:
        flash("Level, category, and area must belong to your organization.", "error")
    return ok
