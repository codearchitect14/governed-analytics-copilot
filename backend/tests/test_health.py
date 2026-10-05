"""Tests for the liveness and readiness probes and request id handling."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.api import health
from app.core.config import Settings, get_settings
from app.main import create_app


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(create_app()) as test_client:
        yield test_client


def test_health_reports_ok(client: TestClient) -> None:
    response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_response_carries_generated_request_id(client: TestClient) -> None:
    response = client.get("/api/v1/health")

    assert len(response.headers["x-request-id"]) == 32


def test_incoming_request_id_is_reused(client: TestClient) -> None:
    response = client.get("/api/v1/health", headers={"X-Request-ID": "trace-123"})

    assert response.headers["x-request-id"] == "trace-123"


def test_unsafe_incoming_request_id_is_replaced(client: TestClient) -> None:
    response = client.get("/api/v1/health", headers={"X-Request-ID": "a" * 65})

    assert response.headers["x-request-id"] != "a" * 65


def test_ready_returns_503_when_database_unreachable(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(health, "check_database", lambda _settings: False)

    response = client.get("/api/v1/ready")

    assert response.status_code == 503
    assert response.json()["checks"]["database"] == "unreachable"


def test_ready_returns_ok_when_database_reachable(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(health, "check_database", lambda _settings: True)

    response = client.get("/api/v1/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "checks": {"database": "ok"}}


def test_settings_default_to_local_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("APP_ENV", raising=False)
    get_settings.cache_clear()
    settings = Settings(_env_file=None)

    assert settings.app_env == "local"
