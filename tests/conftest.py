import os

import pytest

# Force in-memory rate limiter before app import (avoids Redis dependency in tests).
os.environ.setdefault("REDIS_URI", "memory://")


@pytest.fixture
def app():
    os.environ["REDIS_URI"] = "memory://"
    from app import app as flask_app

    flask_app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
    return flask_app


@pytest.fixture
def client(app):
    return app.test_client()
