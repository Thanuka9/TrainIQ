"""Smoke tests for study material routes — catch missing-import NameErrors at runtime."""
import os

import pytest

os.environ.setdefault("REDIS_URI", "memory://")

from models import User


@pytest.fixture
def logged_in_client(app):
    app.config["WTF_CSRF_ENABLED"] = False
    for lim in app.extensions.get("limiter") or ():
        lim.enabled = False
    client = app.test_client()
    with app.app_context():
        user = User.query.filter_by(is_verified=True).first()
        if not user:
            pytest.skip("No verified user in database")
        with client.session_transaction() as sess:
            sess["_user_id"] = str(user.id)
            sess["_fresh"] = True
            sess["user_id"] = user.id
            if user.tenant_id is not None:
                sess["tenant_id"] = user.tenant_id
    return client


def test_list_study_materials_page(logged_in_client):
    resp = logged_in_client.get("/study_materials/list")
    assert resp.status_code == 200


def test_study_materials_dashboard(logged_in_client):
    resp = logged_in_client.get("/study_materials")
    assert resp.status_code == 200


def test_get_dropdowns(logged_in_client):
    resp = logged_in_client.get("/study_materials/get_dropdowns")
    assert resp.status_code == 200
    data = resp.get_json()
    assert "levels" in data
    assert "categories" in data
    assert "designations" in data
