#!/usr/bin/env python3
"""Apply PostgreSQL migrations and ensure MongoDB indexes."""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def main():
    from app import app, db, run_tenant_backfill, run_catalog_backfill
    from mongodb_operations import initialize_mongodb, setup_collections

    print("=== PostgreSQL: running Alembic migrations ===")
    with app.app_context():
        from flask_migrate import upgrade as migrate_upgrade
        migrate_upgrade()
        print("Migrations applied.")

        print("=== PostgreSQL: backfill tenant/catalog data ===")
        run_tenant_backfill()
        run_catalog_backfill()
        from utils.billing_plans import backfill_missing_trial_dates
        backfill_missing_trial_dates()
        from utils.platform_ceo import ensure_platform_ceo
        ensure_platform_ceo()
        db.session.commit()
        print("Backfill complete.")

    print("=== MongoDB: ensure collections and indexes ===")
    from models import Tenant
    from utils.mongo_tenant import provision_tenant_mongo

    _, mongo_db = initialize_mongodb()
    setup_collections(mongo_db)
    with app.app_context():
        for tenant in Tenant.query.all():
            provision_tenant_mongo(tenant.id)
    print("MongoDB indexes ready (legacy + per-tenant databases).")

    print("=== Done ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
