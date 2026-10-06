"""Workspace endpoints: ownership of history and saved questions, feedback, audit, CSV safety."""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient

from app.api.audit_explorer import _cell
from app.audit.writer import AuditEvent, append_event
from app.core.config import get_settings
from app.db.engine import get_engine
from tests.conftest import bearer, login


def _headers(client: TestClient, email: str) -> dict[str, str]:
    return bearer(str(login(client, email)["access_token"]))


def test_saved_questions_belong_to_their_owner(client: TestClient) -> None:
    owner = _headers(client, "analyst@meridian.example")
    other = _headers(client, "executive@meridian.example")
    created = client.post(
        "/api/v1/saved-queries",
        headers=owner,
        json={"title": "Monthly", "question": "Revenue by month"},
    )
    saved_id = created.json()["id"]

    assert created.status_code == 201
    assert any(
        item["id"] == saved_id for item in client.get("/api/v1/saved-queries", headers=owner).json()
    )
    assert all(
        item["id"] != saved_id for item in client.get("/api/v1/saved-queries", headers=other).json()
    )
    assert client.post(f"/api/v1/saved-queries/{saved_id}/run", headers=other).status_code == 404
    assert (
        client.post(f"/api/v1/saved-queries/{saved_id}/run", headers=owner).json()["question"]
        == "Revenue by month"
    )
    assert client.delete(f"/api/v1/saved-queries/{saved_id}", headers=owner).status_code == 204


def test_chat_sessions_are_private_to_the_user(client: TestClient) -> None:
    engine = get_engine(get_settings())
    owner_id = client.get(
        "/api/v1/auth/me", headers=_headers(client, "analyst@meridian.example")
    ).json()["id"]
    session_id = str(uuid.uuid4())
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "INSERT INTO app.chat_sessions (id, user_id, title) VALUES (%s, %s, 'Private')",
            (session_id, owner_id),
        )

    owner_view = client.get(
        f"/api/v1/chat/sessions/{session_id}", headers=_headers(client, "analyst@meridian.example")
    )
    other_view = client.get(
        f"/api/v1/chat/sessions/{session_id}",
        headers=_headers(client, "executive@meridian.example"),
    )

    assert owner_view.status_code == 200
    assert other_view.status_code == 404


def test_feedback_accepts_only_up_or_down(client: TestClient) -> None:
    headers = _headers(client, "analyst@meridian.example")

    ok = client.post("/api/v1/chat/feedback", headers=headers, json={"audit_id": 1, "value": "up"})
    bad = client.post(
        "/api/v1/chat/feedback", headers=headers, json={"audit_id": 1, "value": "meh"}
    )

    assert ok.status_code == 201
    assert bad.status_code == 422


def test_audit_explorer_filters_and_is_admin_only(client: TestClient) -> None:
    engine = get_engine(get_settings())
    marker = f"explorer-{uuid.uuid4().hex[:8]}"
    with engine.begin() as connection:
        append_event(
            connection,
            AuditEvent(event="query", decision="denied", question=marker, denial_reason="test"),
        )

    admin = _headers(client, "admin@meridian.example")
    found = client.get(f"/api/v1/admin/audit?q={marker}", headers=admin).json()
    forbidden = client.get(
        "/api/v1/admin/audit", headers=_headers(client, "analyst@meridian.example")
    )

    assert found["total"] >= 1
    assert all(item["decision"] == "denied" for item in found["items"])
    assert forbidden.status_code == 403


def test_audit_csv_export_neutralises_formulas(client: TestClient) -> None:
    engine = get_engine(get_settings())
    marker = f"=HYPERLINK({uuid.uuid4().hex[:6]})"
    with engine.begin() as connection:
        append_event(connection, AuditEvent(event="query", decision="info", question=marker))

    response = client.get(
        "/api/v1/admin/audit?format=csv&decision=info",
        headers=_headers(client, "admin@meridian.example"),
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert "'=HYPERLINK" in response.text
    assert _cell("=1+1") == "'=1+1"
    assert _cell("plain") == "plain"


def test_catalog_endpoints_return_metrics_and_dimensions(client: TestClient) -> None:
    headers = _headers(client, "analyst@meridian.example")

    metrics = client.get("/api/v1/catalog/metrics", headers=headers).json()
    dims = client.get("/api/v1/catalog/dimensions", headers=headers).json()
    meta = client.get("/api/v1/catalog/meta", headers=headers).json()

    assert any(item["name"] == "revenue" for item in metrics)
    assert any(item["name"] == "order_item__customer_state" for item in dims)
    assert "data_as_of" in meta
