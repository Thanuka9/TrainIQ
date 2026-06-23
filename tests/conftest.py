import os

import pytest

# CI / local test defaults — must be set before app import in test modules.
os.environ["REDIS_URI"] = "memory://"
os.environ["FLASK_ENV"] = "development"
os.environ.setdefault("RUN_SCHEDULER", "false")
os.environ.setdefault("EVENT_BUS_CONSUMER", "false")
os.environ.setdefault("DB_BOOTSTRAP_ON_STARTUP", "false")
os.environ.setdefault("SERVICE_MODE", "full")
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
    app.config["WTF_CSRF_ENABLED"] = False
    for lim in app.extensions.get("limiter") or ():
        lim.enabled = False
    return app.test_client()


@pytest.fixture
def support_staff_user(app):
    """Ephemeral platform support user for route permission tests."""
    import uuid
    from datetime import date

    from extensions import db
    from models import User
    from utils.platform_staff import get_platform_tenant

    with app.app_context():
        tenant = get_platform_tenant()
        assert tenant is not None, "Platform tenant required in test database"
        email = f"test-support-{uuid.uuid4().hex[:8]}@trainiq-test.local"
        user = User(
            first_name="Test",
            last_name="Support",
            employee_email=email,
            employee_id=f"TS{uuid.uuid4().hex[:6].upper()}",
            join_date=date.today(),
            tenant_id=tenant.id,
            is_platform_staff=True,
            platform_staff_role="support",
            is_verified=True,
            privacy_agreed=True,
        )
        user.set_password("TestPass1!")
        db.session.add(user)
        db.session.commit()
        user_id = user.id
        yield user
        User.query.filter_by(id=user_id).delete()
        db.session.commit()


@pytest.fixture
def platform_staff_factory(app):
    """Create ephemeral platform staff users by role."""
    import uuid
    from datetime import date

    from extensions import db
    from models import User
    from utils.platform_staff import get_platform_tenant

    created_ids: list[int] = []

    def _make(role: str = "support"):
        with app.app_context():
            tenant = get_platform_tenant()
            assert tenant is not None, "Platform tenant required in test database"
            email = f"test-{role}-{uuid.uuid4().hex[:8]}@trainiq-test.local"
            user = User(
                first_name="Test",
                last_name=role.title(),
                employee_email=email,
                employee_id=f"T{role[:2].upper()}{uuid.uuid4().hex[:6].upper()}",
                join_date=date.today(),
                tenant_id=tenant.id,
                is_platform_staff=True,
                platform_staff_role=role,
                is_verified=True,
                privacy_agreed=True,
            )
            user.set_password("TestPass1!")
            db.session.add(user)
            db.session.commit()
            created_ids.append(user.id)
            return user

    yield _make

    with app.app_context():
        if created_ids:
            User.query.filter(User.id.in_(created_ids)).delete(synchronize_session=False)
            db.session.commit()
