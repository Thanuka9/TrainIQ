"""Bootstrap per-tenant catalog data (categories, levels, areas, designations)."""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

DEFAULT_CATEGORIES = (
    "General",
    "Compliance",
    "Operations",
    "Technical Skills",
    "Leadership",
)

DEFAULT_LEVELS = (
    (1, "Beginner"),
    (2, "Intermediate"),
    (3, "Advanced"),
    (4, "Expert"),
    (5, "Master"),
)

DEFAULT_AREAS = (
    "Core",
    "Advanced",
    "Specialized",
)

DEFAULT_DESIGNATIONS = (
    ("Associate", 1),
    ("Specialist", 2),
    ("Supervisor", 3),
    ("Manager", 4),
)


def _sync_catalog_sequences() -> None:
    """Keep PostgreSQL serial sequences aligned after manual/backfill inserts."""
    from extensions import db

    for table in ("categories", "levels", "areas", "designations"):
        db.session.execute(
            db.text(
                f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), "
                f"COALESCE((SELECT MAX(id) FROM {table}), 1))"
            )
        )


def seed_tenant_catalog(tenant_id: int) -> None:
    """Create default learning catalog rows scoped to one organization."""
    from extensions import db
    from models import Area, Category, Designation, Level

    if not tenant_id:
        return

    _sync_catalog_sequences()

    for name in DEFAULT_CATEGORIES:
        if not Category.query.filter_by(tenant_id=tenant_id, name=name).first():
            db.session.add(Category(name=name, tenant_id=tenant_id))

    for num, title in DEFAULT_LEVELS:
        if not Level.query.filter_by(tenant_id=tenant_id, level_number=num).first():
            db.session.add(Level(level_number=num, title=title, tenant_id=tenant_id))

    for name in DEFAULT_AREAS:
        if not Area.query.filter_by(tenant_id=tenant_id, name=name).first():
            db.session.add(Area(name=name, tenant_id=tenant_id))

    for title, starting_level in DEFAULT_DESIGNATIONS:
        if not Designation.query.filter_by(tenant_id=tenant_id, title=title).first():
            db.session.add(Designation(title=title, starting_level=starting_level, tenant_id=tenant_id))

    try:
        db.session.commit()
        logger.info("Seeded default catalog for tenant_id=%s", tenant_id)
    except Exception as exc:
        db.session.rollback()
        logger.error("Failed to seed catalog for tenant_id=%s: %s", tenant_id, exc)
        raise
