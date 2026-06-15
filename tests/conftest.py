import os

import pytest

# CI / local test defaults — must be set before app import in test modules.
os.environ.setdefault("REDIS_URI", "memory://")
os.environ.setdefault("FLASK_ENV", "development")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql://postgres:postgres@localhost:5432/collectivercm_test",
)
os.environ.setdefault("TRAINIQ_CEO_DEFAULT_PASSWORD", "test-ceo-password")


@pytest.fixture
def app():
    os.environ["REDIS_URI"] = "memory://"
    from app import app as flask_app

    flask_app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
    return flask_app


@pytest.fixture
def client(app):
    return app.test_client()
