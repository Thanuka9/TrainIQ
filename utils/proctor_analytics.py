"""ProctorIQ analytics helpers for admin dashboards and exports."""
from __future__ import annotations

from models import User, UserScore
from utils.tenant_utils import filter_scores_by_tenant

FLAG_THRESHOLD = 70


def flagged_sessions_query(user):
    """Tenant-scoped query for exam sessions flagged by low trust score."""
    return (
        filter_scores_by_tenant(UserScore.query, user)
        .filter(UserScore.trust_score.isnot(None))
        .filter(UserScore.trust_score < FLAG_THRESHOLD)
        .order_by(UserScore.created_at.desc())
    )


def flagged_session_count(tenant_id):
    """Count flagged proctor sessions for a tenant (or all tenants when None)."""
    q = (
        UserScore.query.filter(UserScore.trust_score.isnot(None))
        .filter(UserScore.trust_score < FLAG_THRESHOLD)
    )
    if tenant_id is not None:
        q = q.join(User, UserScore.user_id == User.id).filter(User.tenant_id == tenant_id)
    return q.count()
