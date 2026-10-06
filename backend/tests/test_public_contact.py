"""Public contact endpoint: validation, honeypot, storage and rate limit."""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app.core.ratelimit import limiter
from tests.conftest import scalar

PAYLOAD = {
    "name": "Ada Lovelace",
    "email": "ada@example.com",
    "company": "Analytical Engines",
    "topic": "Request a walkthrough",
    "message": "Could we see the workspace with a demo account?",
    "consent": True,
}


@pytest.fixture(autouse=True)
def _reset_limiter() -> None:
    limiter.reset()


def test_valid_request_is_stored_and_accepted(client: TestClient) -> None:
    marker = f"{uuid.uuid4().hex[:8]}@example.com"

    response = client.post("/api/v1/public/contact", json={**PAYLOAD, "email": marker})

    assert response.status_code == 202
    assert scalar("SELECT count(*) FROM app.contact_requests WHERE email = :e", {"e": marker}) == 1


@pytest.mark.parametrize(
    "change",
    [
        {"email": "not-an-email"},
        {"message": "too short"},
        {"consent": False},
        {"topic": "Something else"},
        {"name": "A"},
    ],
)
def test_invalid_requests_are_rejected(client: TestClient, change: dict[str, object]) -> None:
    response = client.post("/api/v1/public/contact", json={**PAYLOAD, **change})

    assert response.status_code == 422


def test_honeypot_is_accepted_but_nothing_is_stored(client: TestClient) -> None:
    marker = f"bot-{uuid.uuid4().hex[:8]}@example.com"
    before = int(scalar("SELECT count(*) FROM app.contact_requests") or 0)

    response = client.post(
        "/api/v1/public/contact",
        json={**PAYLOAD, "email": marker, "website": "http://spam.example"},
    )

    assert response.status_code == 202
    assert int(scalar("SELECT count(*) FROM app.contact_requests") or 0) == before


def test_contact_requests_are_rate_limited(client: TestClient) -> None:
    statuses = [
        client.post(
            "/api/v1/public/contact", json={**PAYLOAD, "email": f"r{i}@example.com"}
        ).status_code
        for i in range(6)
    ]

    assert statuses[:5] == [202] * 5
    assert statuses[5] == 429
