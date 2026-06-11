import pytest


@pytest.fixture
def app():
    from app import app as flask_app
    flask_app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
    return flask_app


@pytest.fixture
def client(app):
    return app.test_client()
