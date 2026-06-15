"""Tests for learner course notes."""
import os
from datetime import datetime

import pytest

os.environ.setdefault("REDIS_URI", "memory://")

from unittest.mock import MagicMock, patch

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

from models import db, CourseNote, StudyMaterial, User, Tenant
from utils.ai_cache import make_key


@pytest.fixture
def note_ctx(app):
    with app.app_context():
        tenant = Tenant.query.first()
        if not tenant:
            tenant = Tenant(name="Test Org", allowed_domain="test.local", office_key="TEST")
            db.session.add(tenant)
            db.session.commit()
        user = User.query.filter_by(tenant_id=tenant.id).first()
        if not user:
            pytest.skip("No user in database for note tests")
        material = StudyMaterial.query.filter_by(tenant_id=tenant.id).first()
        if not material:
            material = StudyMaterial(
                title="Note Test Course",
                description="Test",
                tenant_id=tenant.id,
                course_time=1,
                max_time=30,
                minimum_level=1,
                total_pages=1,
            )
            db.session.add(material)
            db.session.commit()
        yield user, material
        CourseNote.query.filter_by(
            user_id=user.id,
            study_material_id=material.id,
            asset_id="asset_test",
        ).delete()
        db.session.commit()


def test_make_key_accepts_video_context():
    key = make_key("summarize", 1, "f1", 2, "youtube", 100, "gemma4:e4b")
    assert len(key) == 64


def test_course_note_upsert_and_unique_scope(app, note_ctx):
    user, material = note_ctx
    note = CourseNote(
        user_id=user.id,
        study_material_id=material.id,
        asset_id="asset_test",
        page_num=3,
        content="First note",
        tenant_id=material.tenant_id,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db.session.add(note)
    db.session.commit()

    loaded = CourseNote.query.filter_by(
        user_id=user.id,
        study_material_id=material.id,
        asset_id="asset_test",
        page_num=3,
    ).one()
    assert loaded.content == "First note"

    loaded.content = "Updated note"
    loaded.updated_at = datetime.utcnow()
    db.session.commit()

    again = CourseNote.query.filter_by(
        user_id=user.id,
        study_material_id=material.id,
        asset_id="asset_test",
        page_num=3,
    ).one()
    assert again.content == "Updated note"


@pytest.fixture
def note_client(note_ctx):
    user, _material = note_ctx
    flask_app.config["TESTING"] = True
    flask_app.config["WTF_CSRF_ENABLED"] = False
    client = flask_app.test_client()
    with client.session_transaction() as sess:
        sess["_user_id"] = str(user.id)
        sess["_fresh"] = True
        sess["tenant_id"] = user.tenant_id
    return client, user


def test_export_course_notes_http(note_client, note_ctx):
    client, user = note_client
    _, material = note_ctx
    resp = client.get(f"/study_materials/course_notes/export/{material.id}")
    assert resp.status_code == 200
    assert resp.mimetype.startswith("text/plain")
    body = resp.get_data(as_text=True)
    assert material.title in body or "My Notes" in body


def test_search_course_notes_http(note_client, note_ctx):
    client, user = note_client
    _, material = note_ctx
    resp = client.get("/study_materials/course_notes/search?q=Updated")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["count"] >= 1
    assert any(n["course_id"] == material.id for n in data["notes"])


def test_search_course_notes_requires_min_length(note_client):
    client, _user = note_client
    resp = client.get("/study_materials/course_notes/search?q=a")
    assert resp.status_code == 200
    assert resp.get_json()["notes"] == []
