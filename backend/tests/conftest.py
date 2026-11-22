"""Test harness: SQLite in-memory DB, in-memory notification senders, temp site storage."""

from __future__ import annotations

import os
import tempfile
from collections.abc import Iterator
from pathlib import Path

# Configure settings before the app is imported.
_SITES_DIR = Path(tempfile.mkdtemp(prefix="gumaweb-sites-"))
os.environ.update(
    {
        "ENVIRONMENT": "test",
        "DATABASE_URL": "sqlite+pysqlite:///:memory:",
        "GENERATED_SITES_DIR": str(_SITES_DIR),
        "JWT_SECRET_KEY": "test-secret-key-with-enough-length-0123456789",
        "SITE_URL_TEMPLATE": "http://sites.test/{subdomain}/",
        "FRONTEND_URL": "http://portal.test",
        "API_PUBLIC_URL": "http://api.test",
    }
)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, event  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.core import rate_limit  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db.seed import seed_plans  # noqa: E402
from app.db.session import get_db  # noqa: E402
from app.domains.customers.enums import UserRole  # noqa: E402
from app.main import app  # noqa: E402
from app.models import User  # noqa: E402
from app.services.notifications import MemoryEmailSender, MemorySmsSender  # noqa: E402
from app.services.providers import providers  # noqa: E402
from app.services.support import SYSTEM  # noqa: E402
from app.services.template_service import TemplateService  # noqa: E402
from tests.fakes import FakeDns  # noqa: E402

# Default: in-memory SQLite (fast). Set TEST_DATABASE_URL to a disposable PostgreSQL database to run the
# same suite against the production dialect (catches GROUP BY / locking / type differences SQLite forgives).
TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
if TEST_DATABASE_URL:
    engine = create_engine(TEST_DATABASE_URL)
else:
    engine = create_engine("sqlite+pysqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)

    @event.listens_for(engine, "connect")
    def _enable_fks(dbapi_connection, _record) -> None:
        dbapi_connection.execute("PRAGMA foreign_keys=ON")


TestingSession = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@pytest.fixture(autouse=True)
def _schema() -> Iterator[None]:
    Base.metadata.create_all(engine)
    rate_limit._limiter = rate_limit.RateLimiter(rate_limit.MemoryBackend())
    providers.reset()
    providers.email = MemoryEmailSender()
    providers.sms = MemorySmsSender()
    providers.dns = FakeDns()  # never hit real DNS from tests
    yield
    Base.metadata.drop_all(engine)


@pytest.fixture
def settings():
    return get_settings()


@pytest.fixture
def db() -> Iterator[Session]:
    session = TestingSession()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def session_factory():
    return TestingSession


@pytest.fixture
def seeded(db: Session, settings) -> Session:
    seed_plans(db)
    TemplateService(db, settings).sync_from_disk(SYSTEM)
    return db


@pytest.fixture
def client(seeded) -> Iterator[TestClient]:
    def _get_db() -> Iterator[Session]:
        session = TestingSession()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = _get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _make_user(db: Session, email: str, role: UserRole, password: str = "Password!2026") -> User:
    user = User(email=email, password_hash=hash_password(password), role=role, is_email_verified=True)
    db.add(user)
    db.commit()
    return user


def _headers(client: TestClient, email: str, password: str = "Password!2026") -> dict[str, str]:
    response = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.fixture
def admin_headers(client: TestClient, db: Session) -> dict[str, str]:
    _make_user(db, "admin@test.io", UserRole.ADMIN)
    return _headers(client, "admin@test.io")


@pytest.fixture
def operator_headers(client: TestClient, db: Session) -> dict[str, str]:
    _make_user(db, "operator@test.io", UserRole.OPERATOR)
    return _headers(client, "operator@test.io")


@pytest.fixture
def readonly_headers(client: TestClient, db: Session) -> dict[str, str]:
    _make_user(db, "readonly@test.io", UserRole.READONLY)
    return _headers(client, "readonly@test.io")


@pytest.fixture
def sites_dir() -> Path:
    return _SITES_DIR


@pytest.fixture
def published_site(client: TestClient, admin_headers: dict[str, str]) -> dict:
    """A plumbing business with a generated and published website."""
    business = client.post(
        "/api/v1/businesses",
        json={"name": "Santos Plumbing Services", "city": "Angeles City", "province": "Pampanga",
              "phone": "0917 555 0102", "email": "santos.plumbing@gmail.com",
              "facebook": "facebook.com/santosplumbing"},
        headers=admin_headers,
    ).json()
    website = client.post(
        "/api/v1/websites/generate", json={"business_id": business["id"], "publish": True}, headers=admin_headers
    )
    assert website.status_code == 201, website.text
    return {"business": business, "website": website.json()}
