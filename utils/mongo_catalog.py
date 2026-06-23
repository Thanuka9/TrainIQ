"""Central catalog for MongoDB collections, indexes, and tenant DB layout."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MongoIndexSpec:
    collection: str
    field: str
    unique: bool
    tier: str
    reason: str


@dataclass(frozen=True)
class MongoCompoundIndexSpec:
    collection: str
    fields: tuple[tuple[str, int], ...]
    unique: bool
    tier: str
    reason: str
    name: str | None = None


@dataclass(frozen=True)
class MongoCollectionSpec:
    name: str
    description: str
    required: bool = True


# Single-field indexes — legacy DB and every tenant DB via setup_collections()
MONGO_INDEX_CATALOG: tuple[MongoIndexSpec, ...] = (
    MongoIndexSpec(
        'profile_pictures', 'user_id', True, 'safe',
        'Unique lookup for learner profile avatars.',
    ),
    MongoIndexSpec(
        'file_metadata', 'study_material_id', False, 'safe',
        'Course file metadata by study material.',
    ),
    MongoIndexSpec(
        'file_metadata', 'tenant_id', False, 'safe',
        'Tenant-scoped file metadata queries.',
    ),
    MongoIndexSpec(
        'file_metadata', 'file_id', False, 'safe',
        'Direct GridFS file_id lookups.',
    ),
    MongoIndexSpec(
        'file_metadata', 'created_at', False, 'safe',
        'Recent uploads listing per tenant/course.',
    ),
)

# Compound indexes for high-volume tenant queries
MONGO_COMPOUND_INDEX_CATALOG: tuple[MongoCompoundIndexSpec, ...] = (
    MongoCompoundIndexSpec(
        'file_metadata',
        (('tenant_id', 1), ('study_material_id', 1)),
        False,
        'safe',
        'Tenant + course file listing (primary hot path).',
        'ix_file_meta_tenant_material',
    ),
    MongoCompoundIndexSpec(
        'file_metadata',
        (('tenant_id', 1), ('created_at', -1)),
        False,
        'safe',
        'Recent uploads per tenant.',
        'ix_file_meta_tenant_created',
    ),
)

MONGO_COLLECTION_CATALOG: tuple[MongoCollectionSpec, ...] = (
    MongoCollectionSpec('profile_pictures', 'User avatar binary storage', required=True),
    MongoCollectionSpec('file_metadata', 'Study material file index → GridFS', required=True),
    MongoCollectionSpec('fs.files', 'GridFS file catalog', required=False),
    MongoCollectionSpec('fs.chunks', 'GridFS file chunks', required=False),
)

GRIDFS_RECOMMENDED_INDEXES: tuple[MongoIndexSpec, ...] = (
    MongoIndexSpec(
        'fs.files', 'metadata.tenant_id', False, 'manual',
        'Speeds tenant-scoped GridFS file listing (if metadata.tenant_id is set).',
    ),
    MongoIndexSpec(
        'fs.files', 'metadata.study_material_id', False, 'manual',
        'Speeds course-scoped GridFS file listing.',
    ),
    MongoIndexSpec(
        'fs.files', 'uploadDate', False, 'safe',
        'GridFS upload date ordering for cleanup and listing.',
    ),
)


def _compound_key_list(fields: tuple[tuple[str, int], ...]) -> list[tuple[str, int]]:
    return list(fields)


def _index_matches_key(index_key: dict, field: str | None = None, fields: tuple | None = None) -> bool:
    if field:
        return field in index_key
    if fields:
        wanted = _compound_key_list(fields)
        got = [(k, int(v)) for k, v in index_key.items()]
        return got == wanted
    return False


def _has_index(coll, *, field: str | None = None, fields: tuple | None = None) -> bool:
    for idx in coll.list_indexes():
        if _index_matches_key(idx.get('key', {}), field=field, fields=fields):
            return True
    return False


def apply_catalog_indexes(database) -> dict[str, int]:
    """Ensure all safe-tier catalog indexes exist on a MongoDB database."""
    applied = failed = 0

    for spec in MONGO_INDEX_CATALOG:
        try:
            coll = database[spec.collection]
            if _has_index(coll, field=spec.field):
                continue
            kwargs: dict[str, Any] = {'unique': True} if spec.unique else {}
            coll.create_index(spec.field, **kwargs)
            applied += 1
        except Exception as exc:
            failed += 1
            logger.warning('Mongo index %s.%s failed: %s', spec.collection, spec.field, exc)

    for spec in MONGO_COMPOUND_INDEX_CATALOG:
        try:
            coll = database[spec.collection]
            if _has_index(coll, fields=spec.fields):
                continue
            kwargs = {'unique': True} if spec.unique else {}
            if spec.name:
                kwargs['name'] = spec.name
            coll.create_index(list(spec.fields), **kwargs)
            applied += 1
        except Exception as exc:
            failed += 1
            logger.warning('Mongo compound index %s failed: %s', spec.collection, exc)

    for spec in GRIDFS_RECOMMENDED_INDEXES:
        if spec.tier != 'safe':
            continue
        try:
            if spec.collection not in database.list_collection_names():
                continue
            coll = database[spec.collection]
            if _has_index(coll, field=spec.field):
                continue
            coll.create_index(spec.field)
            applied += 1
        except Exception as exc:
            failed += 1
            logger.warning('GridFS index %s.%s failed: %s', spec.collection, spec.field, exc)

    return {'applied': applied, 'failed': failed}


def missing_indexes_for_db(db) -> list[dict[str, str]]:
    """Return catalog indexes not yet present on this database."""
    missing: list[dict[str, str]] = []

    for spec in MONGO_INDEX_CATALOG:
        if spec.collection not in db.list_collection_names():
            missing.append({
                'collection': spec.collection,
                'field': spec.field,
                'reason': f"Collection '{spec.collection}' not present yet.",
            })
            continue
        if not _has_index(db[spec.collection], field=spec.field):
            missing.append({
                'collection': spec.collection,
                'field': spec.field,
                'reason': spec.reason,
            })

    for spec in MONGO_COMPOUND_INDEX_CATALOG:
        if spec.collection not in db.list_collection_names():
            continue
        label = '+'.join(f[0] for f in spec.fields)
        if not _has_index(db[spec.collection], fields=spec.fields):
            missing.append({
                'collection': spec.collection,
                'field': label,
                'reason': spec.reason,
            })

    for spec in GRIDFS_RECOMMENDED_INDEXES:
        if spec.collection not in db.list_collection_names():
            continue
        if not _has_index(db[spec.collection], field=spec.field):
            missing.append({
                'collection': spec.collection,
                'field': spec.field,
                'reason': spec.reason,
            })

    return missing
