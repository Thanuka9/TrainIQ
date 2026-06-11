"""In-app notification API."""
from __future__ import annotations

from flask import Blueprint, jsonify, request
from flask_login import current_user, login_required

from utils.notifications import (
    mark_all_read,
    mark_read,
    recent_for_user,
    sync_user_notifications,
    unread_count,
    notify_trainiq_staff,
)

notification_routes = Blueprint("notification_routes", __name__)


@notification_routes.route("/notifications/api")
@login_required
def notifications_api():
    sync_user_notifications(current_user)
    notify_trainiq_staff(current_user)
    items = recent_for_user(current_user.id, limit=30)
    return jsonify(
        {
            "unread_count": unread_count(current_user.id),
            "items": [n.to_dict() for n in items],
        }
    )


@notification_routes.route("/notifications/<int:notification_id>/read", methods=["POST"])
@login_required
def notification_mark_read(notification_id):
    ok = mark_read(notification_id, current_user.id)
    return jsonify({"ok": ok, "unread_count": unread_count(current_user.id)})


@notification_routes.route("/notifications/read-all", methods=["POST"])
@login_required
def notifications_mark_all_read():
    count = mark_all_read(current_user.id)
    return jsonify({"ok": True, "marked": count, "unread_count": 0})
