"""Profile helpers — tenant-scoped performance charts."""
from __future__ import annotations

from utils.tenant_utils import tenant_category_names, tenant_levels_query, tenant_user_id_list, user_tenant_id


def performance_for_level(user, level_number):
    from models import Category, UserScore

    labels, user_scores, avg_scores = [], [], []
    tenant_ids = tenant_user_id_list(user)
    tid = user_tenant_id(user) or user.tenant_id

    for cat_name in tenant_category_names(user):
        labels.append(cat_name)
        cat = Category.query.filter_by(name=cat_name, tenant_id=tid).first()
        if cat:
            scores = UserScore.query.filter_by(
                user_id=user.id, category_id=cat.id, level_id=level_number
            ).all()
            user_scores.append(round(sum(s.score for s in scores) / len(scores), 2) if scores else 0)
            all_q = UserScore.query.filter_by(category_id=cat.id, level_id=level_number)
            if tenant_ids is not None:
                all_q = all_q.filter(UserScore.user_id.in_(tenant_ids))
            all_scores = all_q.all()
            avg_scores.append(round(sum(s.score for s in all_scores) / len(all_scores), 2) if all_scores else 0)
        else:
            user_scores.append(0)
            avg_scores.append(0)
    return labels, user_scores, avg_scores


def tenant_levels_for_user(user):
    from models import Level
    return tenant_levels_query(user).order_by(Level.level_number).all()
