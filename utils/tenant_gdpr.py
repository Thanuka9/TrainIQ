"""Tenant GDPR-style anonymization and optional hard purge."""
from __future__ import annotations

import logging
import uuid

logger = logging.getLogger(__name__)


def anonymize_tenant(tenant, *, actor_user_id: int | None = None, purge_storage: bool = False) -> tuple[bool, str]:
    """
    Anonymize a customer organization.
    When purge_storage=True, also deletes GridFS, profile pics, and tenant-scoped Postgres rows.
    """
    from datetime import datetime

    from extensions import db
    from models import User
    from utils.tenant_utils import is_platform_tenant

    if not tenant:
        return False, 'Tenant not found.'
    if is_platform_tenant(tenant):
        return False, 'Cannot anonymize the TrainIQ platform organization.'

    status = (getattr(tenant, 'status', '') or '').lower()
    if status == 'anonymized':
        return False, 'Tenant is already anonymized.'

    purge_stats = {}
    if purge_storage:
        purge_stats = purge_tenant_storage(tenant.id)

    now = datetime.utcnow()
    original_name = tenant.name
    tenant.name = f'[Deleted] {original_name[:80]}'
    tenant.status = 'anonymized'
    tenant.suspended_at = now
    tenant.suspended_reason = 'GDPR / customer deletion request'
    tenant.stripe_subscription_id = None
    tenant.enable_invite_only = True

    users = User.query.filter_by(tenant_id=tenant.id).filter(User.deleted_at.is_(None)).all()
    for user in users:
        token = uuid.uuid4().hex[:8]
        user.first_name = 'Deleted'
        user.last_name = 'User'
        user.employee_email = f'deleted-{user.id}-{token}@void.trainiq.local'
        user.phone_number = None
        user.employee_id = None
        user.deleted_at = now
        user.is_locked = True
        from werkzeug.security import generate_password_hash
        user.password_hash = generate_password_hash(uuid.uuid4().hex)

    db.session.commit()
    logger.info(
        '[tenant_gdpr] tenant=%s users=%s purge=%s actor=%s',
        tenant.id,
        len(users),
        purge_stats,
        actor_user_id,
    )
    msg = f'Anonymized {len(users)} user(s) for organization formerly known as {original_name}.'
    if purge_storage:
        msg += f' Purged storage: {purge_stats}.'
    return True, msg


def _delete_tenant_rows(model, tenant_id: int) -> int:
    if not hasattr(model, 'tenant_id'):
        return 0
    try:
        return int(
            model.query.filter_by(tenant_id=tenant_id).delete(synchronize_session=False) or 0
        )
    except Exception as exc:
        logger.warning('[tenant_gdpr] postgres purge %s: %s', model.__name__, exc)
        return 0


def purge_tenant_storage(tenant_id: int) -> dict:
    """Hard-delete Mongo GridFS + profile pictures and tenant-scoped Postgres content."""
    from extensions import db
    from models import (
        Announcement,
        Area,
        BillingEvent,
        Category,
        Client,
        CourseNote,
        Department,
        Designation,
        Exam,
        ExamAccessRequest,
        Level,
        LevelArea,
        StudyMaterial,
        SupportTicket,
        Task,
        TenantInvite,
        User,
        UserLevelProgress,
        UserProgress,
        UserScore,
    )

    stats = {'gridfs_files': 0, 'mongo_dropped': False, 'postgres_rows': 0}

    try:
        from gridfs import GridFS
        from utils.mongo_tenant import get_tenant_database, tenant_db_name

        db_mongo = get_tenant_database(tenant_id)
        gfs = GridFS(db_mongo)
        for grid_file in gfs.find():
            gfs.delete(grid_file._id)
            stats['gridfs_files'] += 1
        from mongodb_operations import get_mongo_connection, PROFILE_PICTURES_COLLECTION

        _, legacy_db, _ = get_mongo_connection()
        if legacy_db is not None:
            user_ids = [
                str(row[0])
                for row in User.query.filter_by(tenant_id=tenant_id).with_entities(User.id).all()
            ]
            if user_ids:
                legacy_db[PROFILE_PICTURES_COLLECTION].delete_many({'user_id': {'$in': user_ids}})
        try:
            from mongodb_operations import get_mongo_connection as gmc

            client, _, _ = gmc()
            if client:
                client.drop_database(tenant_db_name(tenant_id))
                stats['mongo_dropped'] = True
        except Exception as exc:
            logger.warning('[tenant_gdpr] drop tenant db: %s', exc)
    except Exception as exc:
        logger.warning('[tenant_gdpr] mongo purge tenant=%s: %s', tenant_id, exc)

    user_ids = [row[0] for row in User.query.filter_by(tenant_id=tenant_id).with_entities(User.id).all()]
    if user_ids:
        for model in (UserScore, ExamAccessRequest, SupportTicket, UserProgress, UserLevelProgress):
            try:
                stats['postgres_rows'] += int(
                    model.query.filter(model.user_id.in_(user_ids)).delete(synchronize_session=False) or 0
                )
            except Exception as exc:
                logger.warning('[tenant_gdpr] postgres purge %s: %s', model.__name__, exc)

    level_ids = [row[0] for row in Level.query.filter_by(tenant_id=tenant_id).with_entities(Level.id).all()]
    if level_ids:
        try:
            stats['postgres_rows'] += int(
                LevelArea.query.filter(LevelArea.level_id.in_(level_ids)).delete(synchronize_session=False) or 0
            )
        except Exception as exc:
            logger.warning('[tenant_gdpr] postgres purge LevelArea: %s', exc)

    for model in (
        CourseNote,
        Announcement,
        BillingEvent,
        TenantInvite,
        Exam,
        StudyMaterial,
        Task,
        Level,
        Area,
        Category,
        Client,
        Department,
        Designation,
    ):
        stats['postgres_rows'] += _delete_tenant_rows(model, tenant_id)

    db.session.commit()
    try:
        from utils.tenant_storage import invalidate_tenant_storage_cache

        invalidate_tenant_storage_cache(tenant_id)
    except Exception:
        pass
    return stats
