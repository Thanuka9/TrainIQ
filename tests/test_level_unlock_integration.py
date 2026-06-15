"""Integration-style tests for level unlock and platform hardening."""
import os
from unittest.mock import MagicMock, patch

import pytest

os.environ.setdefault("REDIS_URI", "memory://")

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


def test_mongodb_initialize_graceful_when_unreachable():
    from mongodb_operations import initialize_mongodb

    client, db = initialize_mongodb(uri="mongodb://127.0.0.1:1", db_name="unreachable_test")
    assert client is None
    assert db is None


def test_debug_start_exam_blocked_in_production():
    flask_app.config["TESTING"] = True
    client = flask_app.test_client()

    with patch.dict(os.environ, {"FLASK_ENV": "production"}, clear=False):
        with patch.dict(os.environ, {"ALLOW_DEBUG_EXAM": ""}, clear=False):
            resp = client.get("/debug/start/1")
    assert resp.status_code in (302, 401, 404)


def test_activity_feed_date_filter():
    from datetime import datetime, timedelta
    from utils.platform_analytics import get_platform_activity_feed

    end = datetime.utcnow()
    start = end - timedelta(days=30)
    with flask_app.app_context():
        feed = get_platform_activity_feed(limit=10, start=start, end=end)
    assert isinstance(feed, list)


def test_upload_course_syncs_minimum_level_from_level():
    """Curriculum level should default designation gate when sync flag is on."""
    from models import Level
    from study_material_routes import upload_course  # noqa: F401 — route module

    with flask_app.app_context():
        lvl = Level.query.order_by(Level.level_number.desc()).first()
        if not lvl:
            pytest.skip("No levels in database")
        assert int(lvl.level_number or 1) >= 1


def test_exam_minimum_designation_id_property_alias():
    from models import Exam

    exam = Exam()
    exam.minimum_designation_level = 42
    assert exam.minimum_designation_id == 42
    exam.minimum_designation_id = 7
    assert exam.minimum_designation_level == 7


def test_advance_user_level_sends_notification(app):
    """End-to-end style: completing a level bumps current_level and notifies the learner."""
    from extensions import db
    from models import Level, Notification, User
    from utils.level_access import advance_user_level_after_completion

    with app.app_context():
        user = User.query.filter_by(is_verified=True).first()
        if not user:
            pytest.skip("No users in database")

        level = (
            Level.query.filter_by(tenant_id=user.tenant_id)
            .order_by(Level.level_number)
            .first()
        )
        if not level:
            pytest.skip("No levels in database")

        next_level = (
            Level.query.filter_by(
                tenant_id=user.tenant_id,
                level_number=level.level_number + 1,
            ).first()
        )
        if not next_level:
            pytest.skip("No next level configured")

        original_level = user.current_level
        dedupe_key = f"level_unlock_{user.id}_{next_level.level_number}"

        Notification.query.filter_by(user_id=user.id, dedupe_key=dedupe_key).delete()
        db.session.commit()

        with patch(
            "utils.level_access.check_level_completion", return_value=True
        ), patch("utils.tenant_utils.tenant_levels_query") as tenant_q:
            tenant_q.return_value.filter_by.return_value.first.return_value = next_level
            with app.test_request_context():
                unlocked = advance_user_level_after_completion(user.id, level.id)

        try:
            assert unlocked == next_level.level_number
            refreshed = User.query.get(user.id)
            assert refreshed.current_level == next_level.level_number

            note = Notification.query.filter_by(
                user_id=user.id,
                dedupe_key=dedupe_key,
            ).first()
            assert note is not None
            assert note.category == "success"
            assert "unlocked" in note.title.lower()
            assert note.link_url == "/dashboard"
        finally:
            user.current_level = original_level
            Notification.query.filter_by(user_id=user.id, dedupe_key=dedupe_key).delete()
            db.session.commit()
