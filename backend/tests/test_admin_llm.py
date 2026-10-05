"""Admin controls for the LLM mode and provider budget status."""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.conftest import bearer, login


def test_admin_can_read_and_change_the_llm_mode(client: TestClient) -> None:
    headers = bearer(str(login(client, "admin@meridian.example")["access_token"]))

    current = client.get("/api/v1/admin/llm", headers=headers)
    changed = client.put("/api/v1/admin/llm/mode", headers=headers, json={"mode": "gemini_only"})
    invalid = client.put("/api/v1/admin/llm/mode", headers=headers, json={"mode": "sometimes"})
    restored = client.put("/api/v1/admin/llm/mode", headers=headers, json={"mode": "auto"})

    assert current.status_code == 200
    assert "providers" in current.json()
    assert changed.status_code == 200
    assert changed.json()["mode"] == "gemini_only"
    assert invalid.status_code == 422
    assert restored.json()["mode"] == "auto"


def test_analyst_cannot_change_the_llm_mode(client: TestClient) -> None:
    headers = bearer(str(login(client, "analyst@meridian.example")["access_token"]))

    response = client.put("/api/v1/admin/llm/mode", headers=headers, json={"mode": "groq_only"})

    assert response.status_code == 403
