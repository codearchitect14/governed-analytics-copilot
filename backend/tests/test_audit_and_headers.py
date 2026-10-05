"""Audit hash chain (append only, tamper detection) and HTTP security headers."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from itertools import pairwise

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.audit.chain import GENESIS_HASH, compute_row_hash
from app.audit.verify import verify_chain
from app.audit.writer import AuditEvent, append_event
from app.core.config import get_settings
from app.db.engine import get_engine
from tests.conftest import execute_admin, login, reset_app_schema, scalar

# ---- canonical hashing (pure) -------------------------------------------------------------


def test_row_hash_does_not_depend_on_timezone_or_key_order() -> None:
    ts = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)
    shifted = ts.astimezone(datetime.now().astimezone().tzinfo or UTC)
    first = compute_row_hash(
        GENESIS_HASH, {"ts": ts, "event": "x", "decision": "info", "plan_json": {"a": 1, "b": 2}}
    )
    second = compute_row_hash(
        GENESIS_HASH,
        {"plan_json": {"b": 2, "a": 1}, "decision": "info", "event": "x", "ts": shifted},
    )

    assert first == second


def test_row_hash_changes_when_any_field_changes() -> None:
    base = {
        "ts": datetime(2026, 1, 1, tzinfo=UTC),
        "event": "x",
        "decision": "info",
        "row_count": 1,
    }
    changed = {**base, "row_count": 2}

    assert compute_row_hash(GENESIS_HASH, base) != compute_row_hash(GENESIS_HASH, changed)


# ---- database behaviour ----------------------------------------------------------------------


def _write_events(count: int) -> None:
    with get_engine(get_settings()).begin() as connection:
        for index in range(count):
            append_event(
                connection,
                AuditEvent(event="test_event", decision="info", denial_reason=f"seq {index}"),
                now=datetime.now(UTC) + timedelta(microseconds=index),
            )


def test_chain_verifies_after_writes(migrated_database: str) -> None:
    _write_events(3)

    with get_engine(get_settings()).connect() as connection:
        report = verify_chain(connection)

    assert report.ok, report.reason
    assert report.rows_checked >= 3


def test_each_row_links_to_the_previous_row_hash(migrated_database: str) -> None:
    _write_events(2)

    rows = (
        get_engine(get_settings())
        .connect()
        .execute(text("SELECT prev_hash, row_hash FROM app.audit_log ORDER BY id"))
        .all()
    )

    assert rows[0][0] == GENESIS_HASH
    for previous, current in pairwise(rows):
        assert current[0] == previous[1]


def test_application_cannot_update_or_delete_audit_rows(migrated_database: str) -> None:
    _write_events(1)
    engine = get_engine(get_settings())

    with pytest.raises(Exception, match="append only"), engine.begin() as connection:
        connection.execute(text("UPDATE app.audit_log SET decision = 'allowed'"))
    with pytest.raises(Exception, match="append only"), engine.begin() as connection:
        connection.execute(text("DELETE FROM app.audit_log"))


def test_tampering_is_detected_and_pinpointed(migrated_database: str) -> None:
    _write_events(3)
    engine = get_engine(get_settings())
    target_id = scalar("SELECT id FROM app.audit_log ORDER BY id DESC LIMIT 1 OFFSET 1")
    original = scalar("SELECT denial_reason FROM app.audit_log WHERE id = :id", {"id": target_id})

    # A superuser disables the guard trigger, edits a row, and restores the trigger.
    execute_admin("ALTER TABLE app.audit_log DISABLE TRIGGER audit_log_no_update_delete")
    try:
        execute_admin(
            "UPDATE app.audit_log SET denial_reason = 'edited after the fact' WHERE id = %(id)s",
            {"id": target_id},
        )
    finally:
        execute_admin("ALTER TABLE app.audit_log ENABLE TRIGGER audit_log_no_update_delete")

    with engine.connect() as connection:
        report = verify_chain(connection)
    assert not report.ok
    assert report.first_invalid_id == target_id
    assert "modified" in str(report.reason)

    # Restore the original content so later tests see an intact chain.
    execute_admin("ALTER TABLE app.audit_log DISABLE TRIGGER audit_log_no_update_delete")
    try:
        execute_admin(
            "UPDATE app.audit_log SET denial_reason = %(value)s WHERE id = %(id)s",
            {"value": original, "id": target_id},
        )
    finally:
        execute_admin("ALTER TABLE app.audit_log ENABLE TRIGGER audit_log_no_update_delete")
    with engine.connect() as connection:
        assert verify_chain(connection).ok


def test_removed_row_breaks_the_link(migrated_database: str) -> None:
    _write_events(3)
    engine = get_engine(get_settings())
    middle = scalar("SELECT id FROM app.audit_log ORDER BY id DESC LIMIT 1 OFFSET 1")
    successor = scalar(
        "SELECT id FROM app.audit_log WHERE id > :id ORDER BY id LIMIT 1", {"id": middle}
    )

    execute_admin("ALTER TABLE app.audit_log DISABLE TRIGGER audit_log_no_update_delete")
    try:
        execute_admin("DELETE FROM app.audit_log WHERE id = %(id)s", {"id": middle})
    finally:
        execute_admin("ALTER TABLE app.audit_log ENABLE TRIGGER audit_log_no_update_delete")

    try:
        with engine.connect() as connection:
            report = verify_chain(connection)
        assert not report.ok
        assert report.first_invalid_id == successor
        assert "link broken" in str(report.reason)
    finally:
        # A deleted audit row cannot be restored, so rebuild the schema for the tests that follow.
        reset_app_schema()


def test_verify_endpoint_reports_the_chain_to_admins(client: TestClient) -> None:
    headers = {"Authorization": f"Bearer {login(client, 'admin@meridian.example')['access_token']}"}

    response = client.get("/api/v1/admin/audit/verify", headers=headers)

    assert response.status_code == 200
    assert response.json()["ok"] is True


# ---- security headers and CORS -----------------------------------------------------------------


def test_security_headers_are_present(client: TestClient) -> None:
    response = client.get("/api/v1/health")

    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "strict-origin-when-cross-origin"
    assert "default-src 'self'" in response.headers["content-security-policy"]
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    assert "max-age=" in response.headers["strict-transport-security"]


def test_cors_allows_only_configured_origins(client: TestClient) -> None:
    allowed = client.options(
        "/api/v1/auth/login",
        headers={
            "Origin": "http://localhost:5180",
            "Access-Control-Request-Method": "POST",
        },
    )
    denied = client.options(
        "/api/v1/auth/login",
        headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"},
    )

    assert allowed.headers.get("access-control-allow-origin") == "http://localhost:5180"
    assert allowed.headers.get("access-control-allow-credentials") == "true"
    assert "access-control-allow-origin" not in denied.headers
