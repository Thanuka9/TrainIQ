"""Tests for in-app notifications."""
import os

os.environ["REDIS_URI"] = "memory://"

from unittest.mock import MagicMock, patch

import pytest

_mongo_patcher = patch(
    "mongodb_operations.initialize_mongodb",
    return_value=(MagicMock(), MagicMock()),
)
_setup_patcher = patch("mongodb_operations.setup_collections")
_mongo_patcher.start()
_setup_patcher.start()

from app import app as flask_app  # noqa: E402

_mongo_patcher.stop()
_setup_patcher.stop()


@pytest.fixture
def auth_client():
    flask_app.config["TESTING"] = True
    flask_app.config["WTF_CSRF_ENABLED"] = False
    from models import User

    with flask_app.app_context():
        user = User.query.filter_by(is_verified=True).first()
        if not user:
            pytest.skip("No users in database")

    client = flask_app.test_client()
    with client.session_transaction() as sess:
        sess["_user_id"] = str(user.id)
        sess["_fresh"] = True
    return client, user


def test_notifications_api(auth_client):
    client, user = auth_client
    resp = client.get("/notifications/api")
    assert resp.status_code == 200
    data = resp.get_json()
    assert "unread_count" in data
    assert "items" in data


def test_create_notification_dedupe(auth_client):
    import uuid

    from extensions import db
    from models import Notification
    from utils.notifications import create_notification

    _, user = auth_client
    key = f"test_dedupe_{user.id}_{uuid.uuid4().hex[:8]}"
    with flask_app.app_context():
        ok1 = create_notification(user.id, "Test alert", "Body", dedupe_key=key)
        ok2 = create_notification(user.id, "Test alert duplicate", "Body", dedupe_key=key)
        assert ok1 is True
        assert ok2 is False
        assert Notification.query.filter_by(user_id=user.id, dedupe_key=key).count() == 1
        db.session.commit()


def test_mark_all_read_stays_read_after_sync(auth_client):
    from extensions import db
    from models import Notification
    from utils.notifications import create_notification, sync_user_notifications, unread_count

    client, user = auth_client
    key = f"test_mark_all_{user.id}"
    with flask_app.app_context():
        Notification.query.filter_by(user_id=user.id, dedupe_key=key).delete()
        Notification.query.filter_by(user_id=user.id, dedupe_key=f"{key}_b").delete()
        db.session.commit()
        create_notification(user.id, "Alert A", "One", dedupe_key=key)
        create_notification(user.id, "Alert B", "Two", dedupe_key=f"{key}_b")
        assert unread_count(user.id) >= 2

    resp = client.post("/notifications/read-all")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"] is True
    assert data["unread_count"] == 0
    assert data.get("items") is not None

    with flask_app.app_context():
        sync_user_notifications(user)
        create_notification(user.id, "Alert A again", "One", dedupe_key=key)
        assert unread_count(user.id) == 0


def test_mark_single_read(auth_client):
    from extensions import db
    from models import Notification
    from utils.notifications import create_notification

    client, user = auth_client
    with flask_app.app_context():
        key = f"test_single_read_{user.id}"
        Notification.query.filter_by(user_id=user.id, dedupe_key=key).delete()
        db.session.commit()
        create_notification(user.id, "Read me", "Body", dedupe_key=key)
        n = Notification.query.filter_by(user_id=user.id, dedupe_key=key).first()
        nid = n.id

    resp = client.post(f"/notifications/{nid}/read")
    assert resp.status_code == 200
    assert resp.get_json()["ok"] is True

    with flask_app.app_context():
        n = db.session.get(Notification, nid)
        assert n.is_read is True
        assert n.read_at is not None
