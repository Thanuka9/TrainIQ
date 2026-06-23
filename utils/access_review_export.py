"""SOC2-style access review export for platform staff and privileged actions."""
from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timedelta
from typing import Any


def build_staff_access_rows() -> list[dict[str, Any]]:
    from utils.platform_staff import list_platform_staff
    from utils.platform_staff_permissions import PERMISSION_LABELS, ROLE_PERMISSIONS
    from utils.tenant_utils import is_platform_ceo

    rows = []
    for user in list_platform_staff():
        role = getattr(user, 'platform_staff_role', None) or 'support'
        if is_platform_ceo(user):
            role = 'ceo'
        perms = sorted(
            ROLE_PERMISSIONS.get(role)
            or (PERMISSION_LABELS.keys() if role == 'ceo' else frozenset())
        )
        rows.append({
            'type': 'staff_account',
            'user_id': user.id,
            'email': user.employee_email,
            'name': f'{user.first_name} {user.last_name}'.strip(),
            'role': role,
            'permissions': ', '.join(perms),
            'is_ceo': is_platform_ceo(user),
            'is_locked': bool(getattr(user, 'is_locked', False)),
        })
    return rows


def build_privileged_audit_rows(*, days: int = 90) -> list[dict[str, Any]]:
    from models import AuditLog, User
    from utils.db_replica import using_analytics_bind

    cutoff = datetime.utcnow() - timedelta(days=max(1, days))
    event_types = (
        'PLATFORM_ENTER_TENANT',
        'PLATFORM_EXIT_TENANT',
        'PLATFORM_SUPPORT_WRITE_ELEVATE',
        'PLATFORM_SUPPORT_ACTION',
        'PLATFORM_ACTIVATE_TENANT',
        'PLATFORM_SUSPEND_TENANT',
        'STRIPE_PLAN_UPGRADE',
        'ORG_DATA_EXPORT',
        'TENANT_GDPR_ANONYMIZE',
    )
    logs = (
        using_analytics_bind(AuditLog.query).filter(AuditLog.created_at >= cutoff)
        .filter(AuditLog.event_type.in_(event_types))
        .order_by(AuditLog.created_at.desc())
        .limit(500)
        .all()
    )
    rows = []
    for log in logs:
        actor = using_analytics_bind(User.query).get(log.actor_user_id) if log.actor_user_id else None
        meta = log.description if isinstance(log.description, dict) else {}
        if isinstance(log.description, str):
            try:
                meta = json.loads(log.description)
            except Exception:
                meta = {'raw': log.description}
        rows.append({
            'type': 'audit_event',
            'event_type': log.event_type,
            'created_at': log.created_at.isoformat() if log.created_at else '',
            'actor_email': actor.employee_email if actor else '',
            'actor_id': log.actor_user_id or '',
            'tenant_id': meta.get('tenant_id', ''),
            'details': json.dumps(meta)[:500] if meta else '',
        })
    return rows


def access_review_csv(*, audit_days: int = 90) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([
        'record_type', 'user_id', 'email', 'name', 'role', 'permissions',
        'is_ceo', 'is_locked', 'event_type', 'created_at', 'tenant_id', 'details',
    ])
    for row in build_staff_access_rows():
        writer.writerow([
            row['type'], row['user_id'], row['email'], row['name'], row['role'],
            row['permissions'], row['is_ceo'], row['is_locked'],
            '', '', '', '',
        ])
    for row in build_privileged_audit_rows(days=audit_days):
        writer.writerow([
            row['type'], row.get('actor_id', ''), row.get('actor_email', ''), '',
            '', '', '', '',
            row['event_type'], row['created_at'], row['tenant_id'], row['details'],
        ])
    return buf.getvalue()
