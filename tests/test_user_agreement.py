"""User Agreement enforcement tests."""
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
        user.user_agreement_version = None
        user.user_agreement_at = None
        from extensions import db
        db.session.commit()
        user_id = user.id

    client = flask_app.test_client()
    with client.session_transaction() as sess:
        sess["_user_id"] = str(user_id)
        sess["_fresh"] = True
    return client, user_id


def test_dashboard_redirects_without_agreement(auth_client):
    client, _user = auth_client
    resp = client.get("/dashboard", follow_redirects=False)
    assert resp.status_code in (301, 302)
    assert "user-agreement" in resp.headers.get("Location", "")


def test_accept_agreement_grants_access(auth_client):
    client, user_id = auth_client
    resp = client.post("/user-agreement/accept", follow_redirects=False)
    assert resp.status_code in (301, 302)

    with flask_app.app_context():
        from extensions import db
        from models import User, UserAgreementAcceptance
        from utils.user_agreement import CURRENT_AGREEMENT_VERSION

        u = db.session.get(User, user_id)
        assert u.user_agreement_version == CURRENT_AGREEMENT_VERSION
        assert u.user_agreement_at is not None
        assert UserAgreementAcceptance.query.filter_by(user_id=user_id).count() >= 1

    resp2 = client.get("/dashboard", follow_redirects=False)
    assert resp2.status_code == 200


def test_public_user_agreement_page():
    flask_app.config["TESTING"] = True
    client = flask_app.test_client()
    resp = client.get("/user-agreement")
    assert resp.status_code == 200
    assert b"Intellectual Property" in resp.data or b"intellectual property" in resp.data.lower()
    assert b"thanukaellepola.careers" in resp.data
    assert b"Thanuka Ellepola" in resp.data
    assert b"Veyra Labs" in resp.data
    assert b"non-refundable" in resp.data.lower()
    assert b"Your documents, your property" in resp.data or b"User Content is yours" in resp.data
    assert b"legal-sidebar" in resp.data
    assert b"legal-progress" in resp.data
