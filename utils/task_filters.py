"""SQLAlchemy filters for Task ↔ User many-to-many assignees."""
from sqlalchemy import or_

from models import Task


def assigned_to_user(user_id):
    """Tasks where user_id is in assignees."""
    return Task.assignees.any(id=user_id)


def involves_user(user_id):
    """Tasks assigned to user or created by user."""
    return or_(Task.assignees.any(id=user_id), Task.assigned_by == user_id)


def user_is_assignee(task, user):
    if not task or not user:
        return False
    return any(a.id == user.id for a in (task.assignees or []))
