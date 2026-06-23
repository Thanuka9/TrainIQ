"""Per-tenant storage usage (GridFS, profile pictures, task attachments) and quota checks."""
from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

STORAGE_CACHE_SECONDS = float(os.getenv('TENANT_STORAGE_CACHE_SECONDS', '60'))


def _gridfs_bytes(tenant_id: int) -> int:
    from mongodb_operations import get_mongo_read_connection
    from utils.mongo_tenant import get_tenant_database

    client, _, _ = get_mongo_read_connection()
    if not client:
        return 0
    db = get_tenant_database(tenant_id)
    try:
        if 'fs.files' not in db.list_collection_names():
            return 0
        pipe = [{'$group': {'_id': None, 'bytes': {'$sum': '$length'}}}]
        agg = list(db['fs.files'].aggregate(pipe))
        if agg:
            return int(agg[0].get('bytes') or 0)
    except Exception as exc:
        logger.debug('[tenant_storage] gridfs stats tenant=%s: %s', tenant_id, exc)
    return 0


def _profile_picture_bytes(tenant_id: int) -> int:
    from models import User
    from mongodb_operations import PROFILE_PICTURES_COLLECTION, get_mongo_read_connection

    _, db, _ = get_mongo_read_connection()
    if not db:
        return 0
    user_ids = [
        str(row[0])
        for row in User.query.filter_by(tenant_id=tenant_id)
        .with_entities(User.id)
        .all()
    ]
    if not user_ids:
        return 0
    total = 0
    try:
        for doc in db[PROFILE_PICTURES_COLLECTION].find(
            {'user_id': {'$in': user_ids}},
            {'image_data': 1},
        ):
            data = doc.get('image_data')
            if data:
                total += len(data)
    except Exception as exc:
        logger.debug('[tenant_storage] profile pics tenant=%s: %s', tenant_id, exc)
    return total


def _task_attachment_bytes(tenant_id: int) -> int:
    from sqlalchemy import func

    from extensions import db
    from models import Task, TaskDocument

    try:
        total = (
            db.session.query(func.coalesce(func.sum(func.length(TaskDocument.data)), 0))
            .join(Task, TaskDocument.task_id == Task.id)
            .filter(Task.tenant_id == tenant_id)
            .scalar()
        )
        return int(total or 0)
    except Exception as exc:
        logger.debug('[tenant_storage] task attachments tenant=%s: %s', tenant_id, exc)
        return 0


def _compute_storage_usage(tenant_id: int, *, max_storage_mb: int) -> dict:
    gridfs = _gridfs_bytes(tenant_id)
    profiles = _profile_picture_bytes(tenant_id)
    tasks = _task_attachment_bytes(tenant_id)
    used_bytes = gridfs + profiles + tasks
    max_bytes = max(1, int(max_storage_mb)) * 1024 * 1024
    used_mb = round(used_bytes / (1024 * 1024), 2)
    pct = min(100, int((used_bytes / max_bytes) * 100)) if max_bytes else 0
    return {
        'used_bytes': used_bytes,
        'used_mb': used_mb,
        'max_storage_mb': max_storage_mb,
        'max_bytes': max_bytes,
        'usage_percent': pct,
        'at_limit': used_bytes >= max_bytes,
        'breakdown': {
            'gridfs_bytes': gridfs,
            'profile_bytes': profiles,
            'task_bytes': tasks,
        },
    }


def get_tenant_storage_usage(tenant_id: int, tenant=None) -> dict:
    """Cached storage snapshot for a tenant."""
    from utils.tenant_limits import get_tenant_limits

    if tenant is None:
        from models import Tenant

        tenant = Tenant.query.get(tenant_id)
    limits = get_tenant_limits(tenant)
    max_mb = int(limits.get('max_storage_mb') or 2048)
    cache_key = f'tenant_storage:{tenant_id}'

    from utils.ops_cache import get_json_cached

    return get_json_cached(
        cache_key,
        STORAGE_CACHE_SECONDS,
        lambda: _compute_storage_usage(tenant_id, max_storage_mb=max_mb),
    )


def invalidate_tenant_storage_cache(tenant_id: int) -> None:
    from utils.ops_cache import invalidate_json_cached

    invalidate_json_cached(f'tenant_storage:{tenant_id}')


def check_storage_quota(tenant, additional_bytes: int) -> tuple[bool, str]:
    """Return (allowed, message). additional_bytes is the incoming upload size."""
    if not tenant:
        return False, 'Organization not found.'
    from utils.tenant_limits import get_tenant_limits

    limits = get_tenant_limits(tenant)
    max_mb = int(limits.get('max_storage_mb') or 2048)
    usage = get_tenant_storage_usage(tenant.id, tenant=tenant)
    projected = usage['used_bytes'] + max(0, int(additional_bytes))
    if projected > usage['max_bytes']:
        return (
            False,
            f'Storage limit reached ({usage["used_mb"]:.1f}/{max_mb} MB). '
            'Upgrade your plan in Billing to upload more files.',
        )
    return True, ''


def assert_storage_allowed(tenant, additional_bytes: int) -> bool:
    """Flash and return False when quota would be exceeded."""
    from flask import flash

    ok, msg = check_storage_quota(tenant, additional_bytes)
    if not ok:
        flash(msg, 'error')
    return ok


def sum_upload_file_sizes(file_list) -> int:
    """Total byte size of werkzeug FileStorage items without consuming streams."""
    total = 0
    for f in file_list or []:
        if not f or not getattr(f, 'filename', None):
            continue
        try:
            pos = f.tell()
            data = f.read()
            total += len(data)
            f.seek(pos)
        except Exception:
            continue
    return total
