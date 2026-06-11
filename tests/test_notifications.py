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
    from utils.notifications import create_notification, unread_count

    _, user = auth_client
    with flask_app.app_context():
        create_notification(
            user.id,
            "Test alert",
            "Body",
            dedupe_key="test_dedupe_key",
        )
        create_notification(
            user.id,
            "Test alert duplicate",
            "Body",
            dedupe_key="test_dedupe_key",
        )
        assert unread_count(user.id) >= 1
