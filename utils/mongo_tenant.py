"""Per-tenant MongoDB databases and GridFS buckets."""
from __future__ import annotations

import logging
import os

from gridfs import GridFS
from pymongo.database import Database

logger = logging.getLogger(__name__)

LEGACY_DB_NAME = os.getenv("MONGO_DB_NAME", "collective_rcm")
MONGO_TENANT_PREFIX = os.getenv("MONGO_TENANT_DB_PREFIX", "trainiq_t")


def tenant_db_name(tenant_id: int | None) -> str:
    if tenant_id is None:
        return LEGACY_DB_NAME
    return f"{MONGO_TENANT_PREFIX}{int(tenant_id)}"


def get_tenant_database(tenant_id: int | None) -> Database:
    from mongodb_operations import get_mongo_connection

    client, _, _ = get_mongo_connection()
    return client[tenant_db_name(tenant_id)]


def get_tenant_gridfs(tenant_id: int | None) -> GridFS:
    return GridFS(get_tenant_database(tenant_id))


def provision_tenant_mongo(tenant_id: int):
    """Create tenant DB and indexes."""
    from mongodb_operations import setup_collections

    db = get_tenant_database(tenant_id)
    setup_collections(db)
    logger.info("Provisioned MongoDB database %s", db.name)


def get_gridfs_for_material(material) -> GridFS:
    tid = getattr(material, "tenant_id", None)
    return get_tenant_gridfs(tid)


def open_grid_file(file_id, tenant_id=None):
    """
    Open GridFS file from tenant DB, falling back to legacy shared DB.
    Returns (grid_file, gridfs_instance).
    """
    from bson.objectid import ObjectId

    oid = ObjectId(file_id)
    tried = []
    for tid in (tenant_id, None):
        if tid in tried:
            continue
        tried.append(tid)
        gfs = get_tenant_gridfs(tid)
        try:
            return gfs.get(oid), gfs
        except Exception:
            continue
    raise FileNotFoundError(f"GridFS file not found: {file_id}")
