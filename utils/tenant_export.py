"""Tenant data export for org admins and platform operators (GDPR / portability)."""
from __future__ import annotations

from datetime import datetime
from typing import Any


def build_tenant_export(tenant_id: int, *, include_users: bool = True) -> dict[str, Any] | None:
    """Build a JSON-serializable export of tenant metadata and records (no secrets)."""
    from models import (
        Client,
        Department,
        Designation,
        Exam,
        StudyMaterial,
        Task,
        Tenant,
        User,
        UserScore,
    )

    tenant = Tenant.query.get(tenant_id)
    if not tenant:
        return None

    payload: dict[str, Any] = {
        'exported_at': datetime.utcnow().isoformat() + 'Z',
        'tenant': {
            'id': tenant.id,
            'name': tenant.name,
            'office_key': tenant.office_key,
            'plan': tenant.plan,
            'status': tenant.status,
            'billing_cycle': tenant.billing_cycle,
            'max_users': tenant.max_users,
            'max_storage_mb': tenant.max_storage_mb,
            'created_at': tenant.created_at.isoformat() if tenant.created_at else None,
        },
        'counts': {},
    }

    if include_users:
        users = User.query.filter_by(tenant_id=tenant_id).filter(User.deleted_at.is_(None)).all()
        payload['users'] = [
            {
                'id': u.id,
                'employee_email': u.employee_email,
                'first_name': u.first_name,
                'last_name': u.last_name,
                'employee_id': u.employee_id,
                'is_super_admin': u.is_super_admin,
                'is_verified': u.is_verified,
                'join_date': u.join_date.isoformat() if u.join_date else None,
            }
            for u in users
        ]
        payload['counts']['users'] = len(users)

    payload['courses'] = [
        {
            'id': c.id,
            'title': c.title,
            'description': (c.description or '')[:500],
            'hours': c.course_time,
        }
        for c in StudyMaterial.query.filter_by(tenant_id=tenant_id).all()
    ]
    payload['exams'] = [
        {
            'id': e.id,
            'title': e.title,
            'passing_score': e.passing_score,
            'time_limit': e.time_limit,
        }
        for e in Exam.query.filter_by(tenant_id=tenant_id).all()
    ]
    payload['tasks'] = [
        {
            'id': t.id,
            'title': t.title,
            'status': t.status,
            'due_date': t.due_date.isoformat() if t.due_date else None,
        }
        for t in Task.query.filter_by(tenant_id=tenant_id).all()
    ]
    payload['departments'] = [
        {'id': d.id, 'name': d.name}
        for d in Department.query.filter_by(tenant_id=tenant_id).all()
    ]
    payload['designations'] = [
        {'id': d.id, 'title': d.title}
        for d in Designation.query.filter_by(tenant_id=tenant_id).all()
    ]
    payload['clients'] = [
        {'id': c.id, 'name': c.name}
        for c in Client.query.filter_by(tenant_id=tenant_id).all()
    ]

    exam_ids = [e['id'] for e in payload['exams']]
    if exam_ids:
        scores = UserScore.query.filter(UserScore.exam_id.in_(exam_ids)).all()
        payload['exam_scores'] = [
            {
                'user_id': s.user_id,
                'exam_id': s.exam_id,
                'score': s.score,
                'submitted_at': s.submitted_at.isoformat() if s.submitted_at else None,
            }
            for s in scores
        ]
    else:
        payload['exam_scores'] = []

    try:
        from utils.tenant_storage import get_tenant_storage_usage

        payload['storage'] = get_tenant_storage_usage(tenant_id, tenant=tenant)
    except Exception:
        payload['storage'] = None

    payload['counts'].update({
        'courses': len(payload['courses']),
        'exams': len(payload['exams']),
        'tasks': len(payload['tasks']),
    })
    return payload
