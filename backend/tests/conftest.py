"""Shared fixtures.

Integration tests need PostgreSQL. They use a dedicated database (TEST_DATABASE_URL, default
copilot_test) and reset its app schema once per session. The superuser connection
(TEST_ADMIN_DATABASE_URL) is used only for that reset and for the tamper test.

Settings are read from the environment when the application is imported, so the test
environment is prepared before any app module is loaded.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = Path(__file__).resolve().parents[1]
DEMO_PASSWORD = "DemoOnly-Meridian-2026"
TEST_JWT_SECRET = "test-only-secret-that-is-long-enough-for-hs256-0123456789"


def _load_dotenv(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key.strip()] = value.strip()
    return values


_dotenv = _load_dotenv(REPO_ROOT / ".env")
_superuser_password = os.environ.get(
    "POSTGRES_SUPERUSER_PASSWORD", _dotenv.get("POSTGRES_SUPERUSER_PASSWORD", "")
)
_app_password = os.environ.get("APP_RW_DB_PASSWORD", _dotenv.get("APP_RW_DB_PASSWORD", ""))

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    f"postgresql://app_rw:{_app_password}@localhost:5433/copilot_test",
)
TEST_ADMIN_DATABASE_URL = os.environ.get(
    "TEST_ADMIN_DATABASE_URL",
    f"postgresql://postgres:{_superuser_password}@localhost:5433/copilot_test",
)

os.environ["APP_ENV"] = "test"
os.environ["APP_DATABASE_URL"] = TEST_DATABASE_URL
os.environ["JWT_SECRET"] = TEST_JWT_SECRET
os.environ["COOKIE_SECURE"] = "true"
os.environ["DEMO_USER_PASSWORD"] = DEMO_PASSWORD
os.environ.setdefault("LOG_LEVEL", "WARNING")
# Warehouse credentials for the query pipeline tests (MetricFlow reads them through dbt profiles)
for _key in (
    "WAREHOUSE_RO_DB_PASSWORD",
    "LOADER_DB_PASSWORD",
    "WAREHOUSE_RO_DATABASE_URL",
    "POSTGRES_DB",
):
    if _dotenv.get(_key) and _key not in os.environ:
        os.environ[_key] = _dotenv[_key]
os.environ.setdefault("LOADER_DB_HOST", "localhost")
os.environ.setdefault("LOADER_DB_PORT", "5433")

import psycopg  # noqa: E402
import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import Engine, text  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.core.ratelimit import limiter  # noqa: E402
from app.db import seed  # noqa: E402
from app.db.engine import get_engine  # noqa: E402
from app.main import create_app  # noqa: E402


def _database_reachable(url: str) -> bool:
    try:
        with psycopg.connect(url.replace("+psycopg", ""), connect_timeout=3) as connection:
            connection.execute("SELECT 1")
        return True
    except psycopg.Error:
        return False


@pytest.fixture(scope="session")
def database_ready() -> str:
    if not _database_reachable(TEST_DATABASE_URL):
        pytest.skip(f"test database not reachable: {TEST_DATABASE_URL.split('@')[-1]}")
    return TEST_DATABASE_URL


def reset_app_schema() -> None:
    """Drop and recreate the app schema, then apply migrations and seed roles and demo users."""
    with psycopg.connect(TEST_ADMIN_DATABASE_URL.replace("+psycopg", ""), autocommit=True) as admin:
        admin.execute("DROP SCHEMA IF EXISTS app CASCADE")
        admin.execute("CREATE SCHEMA app AUTHORIZATION app_rw")
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    get_settings.cache_clear()
    command.upgrade(config, "head")
    engine = get_engine(get_settings())
    with engine.begin() as connection:
        seed.seed_roles(connection)
        seed.seed_demo_users(connection, DEMO_PASSWORD)


@pytest.fixture(scope="session")
def migrated_database(database_ready: str) -> str:
    reset_app_schema()
    return database_ready


@pytest.fixture(scope="session")
def app_instance(migrated_database: str):  # type: ignore[no-untyped-def]
    return create_app()


@pytest.fixture
def client(app_instance) -> Iterator[TestClient]:  # type: ignore[no-untyped-def]
    limiter.reset()
    # https base URL so that Secure cookies are sent back by the test client
    with TestClient(app_instance, base_url="https://testserver") as test_client:
        yield test_client


@pytest.fixture
def engine(migrated_database: str) -> Engine:
    return get_engine(get_settings())


def login(client: TestClient, email: str, password: str = DEMO_PASSWORD) -> dict[str, object]:
    response = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return response.json()


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def execute_admin(sql: str, params: dict[str, object] | None = None) -> None:
    """Run SQL as the superuser (autocommit). Used only by tests that simulate tampering or time."""
    with psycopg.connect(TEST_ADMIN_DATABASE_URL.replace("+psycopg", ""), autocommit=True) as conn:
        conn.execute(sql, params or {})  # type: ignore[arg-type]


def scalar(sql: str, params: dict[str, object] | None = None) -> object:
    with get_engine(get_settings()).connect() as connection:
        return connection.execute(text(sql), params or {}).scalar()
