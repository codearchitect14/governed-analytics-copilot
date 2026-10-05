"""Authentication: login, lockout, token expiry, refresh rotation, reuse revocation and logout."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.api import auth as auth_api
from app.core.config import get_settings
from app.core.ratelimit import limiter
from app.core.security import hash_password
from app.db.engine import get_engine
from tests.conftest import DEMO_PASSWORD, TEST_JWT_SECRET, bearer, execute_admin, login, scalar

REFRESH_COOKIE = "refresh_token"


def _unique_email(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}@meridian.example"


@pytest.fixture
def analyst_email(engine: object) -> str:
    """A dedicated analyst account so tests never disturb the shared demo accounts."""
    email = _unique_email("analyst")
    with get_engine(get_settings()).begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO app.users (email, full_name, password_hash, role, scopes)
                VALUES (:email, 'Test Analyst', :hash, 'analyst', '{}'::jsonb)
                """
            ),
            {"email": email, "hash": hash_password(DEMO_PASSWORD)},
        )
    return email


# ---- login ------------------------------------------------------------------------------------


def test_login_returns_access_token_and_sets_hardened_refresh_cookie(client: TestClient) -> None:
    response = client.post(
        "/api/v1/auth/login", json={"email": "analyst@meridian.example", "password": DEMO_PASSWORD}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["user"]["role"] == "analyst"
    cookie = response.headers["set-cookie"].lower()
    assert "refresh_token=" in cookie
    assert "httponly" in cookie
    assert "secure" in cookie
    assert "samesite=strict" in cookie
    assert "path=/api/v1/auth" in cookie
    assert response.headers["cache-control"] == "no-store"


def test_me_returns_the_authenticated_user(client: TestClient) -> None:
    tokens = login(client, "analyst@meridian.example")

    response = client.get("/api/v1/auth/me", headers=bearer(str(tokens["access_token"])))

    assert response.status_code == 200
    assert response.json()["email"] == "analyst@meridian.example"


def test_wrong_password_and_unknown_email_return_the_same_message(client: TestClient) -> None:
    wrong = client.post(
        "/api/v1/auth/login",
        json={"email": "analyst@meridian.example", "password": "not-the-password"},
    )
    unknown = client.post(
        "/api/v1/auth/login",
        json={"email": "nobody@meridian.example", "password": "not-the-password"},
    )

    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()


def test_password_is_stored_with_argon2id() -> None:
    stored = scalar("SELECT password_hash FROM app.users WHERE email = 'analyst@meridian.example'")

    assert str(stored).startswith("$argon2id$")


def test_protected_route_requires_a_token(client: TestClient) -> None:
    response = client.get("/api/v1/auth/me")

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_tampered_access_token_is_rejected(client: TestClient) -> None:
    tokens = login(client, "analyst@meridian.example")
    forged = jwt.encode(
        {
            "sub": "x",
            "role": "admin",
            "policy_version": 1,
            "jti": "j",
            "iat": 1,
            "exp": 2**31,
            "iss": "meridian-data-copilot",
        },
        "a-different-secret-of-sufficient-length-0123456789",
        algorithm="HS256",
    )

    assert client.get("/api/v1/auth/me", headers=bearer(forged)).status_code == 401
    assert (
        client.get("/api/v1/auth/me", headers=bearer(str(tokens["access_token"]))).status_code
        == 200
    )


# ---- access token expiry ------------------------------------------------------------------------


def test_access_token_lifetime_is_fifteen_minutes(client: TestClient) -> None:
    tokens = login(client, "analyst@meridian.example")
    expires = datetime.fromisoformat(str(tokens["expires_at"]))
    remaining = expires - datetime.now(UTC)

    assert timedelta(minutes=14) < remaining <= timedelta(minutes=15)


def test_expired_access_token_is_rejected(client: TestClient) -> None:
    user_id = scalar("SELECT id::text FROM app.users WHERE email = 'analyst@meridian.example'")
    past = datetime.now(UTC) - timedelta(minutes=30)
    expired = jwt.encode(
        {
            "sub": str(user_id),
            "role": "analyst",
            "policy_version": 1,
            "jti": uuid.uuid4().hex,
            "iat": int((past).timestamp()),
            "exp": int((past + timedelta(minutes=15)).timestamp()),
            "iss": "meridian-data-copilot",
        },
        TEST_JWT_SECRET,
        algorithm="HS256",
    )

    response = client.get("/api/v1/auth/me", headers=bearer(expired))

    assert response.status_code == 401
    assert "expired" in response.json()["detail"].lower()


# ---- lockout ----------------------------------------------------------------------------------


def test_account_locks_after_five_failures_and_correct_password_is_refused(
    client: TestClient, analyst_email: str
) -> None:
    for _ in range(get_settings().lockout_threshold):
        client.post(
            "/api/v1/auth/login", json={"email": analyst_email, "password": "wrong-password-1"}
        )

    locked = client.post(
        "/api/v1/auth/login", json={"email": analyst_email, "password": DEMO_PASSWORD}
    )

    assert locked.status_code == 401
    until = scalar(
        "SELECT locked_until FROM app.users WHERE lower(email) = lower(:e)", {"e": analyst_email}
    )
    assert until is not None
    assert (
        scalar(
            "SELECT count(*) FROM app.audit_log WHERE event = 'account_locked' AND user_id = "
            "(SELECT id FROM app.users WHERE lower(email) = lower(:e))",
            {"e": analyst_email},
        )
        == 1
    )


def test_lockout_expires_and_successful_login_resets_counter(
    client: TestClient, analyst_email: str
) -> None:
    for _ in range(get_settings().lockout_threshold):
        client.post(
            "/api/v1/auth/login", json={"email": analyst_email, "password": "wrong-password-1"}
        )
    execute_admin(
        "UPDATE app.users SET locked_until = now() - interval '1 minute' WHERE lower(email) = lower(%(e)s)",
        {"e": analyst_email},
    )

    response = client.post(
        "/api/v1/auth/login", json={"email": analyst_email, "password": DEMO_PASSWORD}
    )

    assert response.status_code == 200
    assert (
        scalar(
            "SELECT failed_login_count FROM app.users WHERE lower(email) = lower(:e)",
            {"e": analyst_email},
        )
        == 0
    )


# ---- refresh rotation and reuse -------------------------------------------------------------


def test_refresh_rotates_the_token(client: TestClient) -> None:
    first = login(client, "analyst@meridian.example")
    first_cookie = client.cookies.get(REFRESH_COOKIE)

    response = client.post("/api/v1/auth/refresh")

    assert response.status_code == 200
    assert response.json()["access_token"] != first["access_token"]
    assert client.cookies.get(REFRESH_COOKIE) != first_cookie


def test_reusing_a_rotated_refresh_token_revokes_the_whole_family(client: TestClient) -> None:
    login(client, "analyst@meridian.example")
    original = client.cookies.get(REFRESH_COOKIE)
    assert client.post("/api/v1/auth/refresh").status_code == 200
    rotated = client.cookies.get(REFRESH_COOKIE)

    # An attacker replays the token that was already rotated
    client.cookies.set(REFRESH_COOKIE, str(original), path="/api/v1/auth")
    replay = client.post("/api/v1/auth/refresh")

    assert replay.status_code == 401
    # The legitimate successor is revoked too
    client.cookies.set(REFRESH_COOKIE, str(rotated), path="/api/v1/auth")
    assert client.post("/api/v1/auth/refresh").status_code == 401
    assert scalar("SELECT count(*) FROM app.audit_log WHERE event = 'refresh_reuse_detected'") >= 1


def test_refresh_token_expiry_is_enforced(client: TestClient) -> None:
    login(client, "analyst@meridian.example")
    token_row = scalar(
        "SELECT rt.id::text FROM app.refresh_tokens rt JOIN app.users u ON u.id = rt.user_id "
        "WHERE lower(u.email) = 'analyst@meridian.example' AND revoked_at IS NULL "
        "AND used_at IS NULL ORDER BY issued_at DESC LIMIT 1"
    )
    execute_admin(
        "UPDATE app.refresh_tokens SET expires_at = now() - interval '1 second' WHERE id = %(id)s::uuid",
        {"id": token_row},
    )

    assert client.post("/api/v1/auth/refresh").status_code == 401


def test_refresh_without_cookie_is_rejected(client: TestClient) -> None:
    client.cookies.clear()

    assert client.post("/api/v1/auth/refresh").status_code == 401


def test_logout_revokes_the_session(client: TestClient) -> None:
    login(client, "analyst@meridian.example")
    cookie = client.cookies.get(REFRESH_COOKIE)

    logout = client.post("/api/v1/auth/logout")

    assert logout.status_code == 204
    client.cookies.set(REFRESH_COOKIE, str(cookie), path="/api/v1/auth")
    assert client.post("/api/v1/auth/refresh").status_code == 401


# ---- account and policy state -----------------------------------------------------------------


def test_disabled_account_cannot_log_in(client: TestClient, analyst_email: str) -> None:
    execute_admin(
        "UPDATE app.users SET is_active = false WHERE lower(email) = lower(%(e)s)",
        {"e": analyst_email},
    )

    response = client.post(
        "/api/v1/auth/login", json={"email": analyst_email, "password": DEMO_PASSWORD}
    )

    assert response.status_code == 401


def test_token_is_rejected_after_the_role_policy_changes(client: TestClient) -> None:
    tokens = login(client, "analyst@meridian.example")
    headers = bearer(str(tokens["access_token"]))
    assert client.get("/api/v1/auth/me", headers=headers).status_code == 200

    execute_admin("UPDATE app.role_policies SET version = version + 1 WHERE role = 'analyst'")
    try:
        assert client.get("/api/v1/auth/me", headers=headers).status_code == 401
    finally:
        execute_admin("UPDATE app.role_policies SET version = version - 1 WHERE role = 'analyst'")


def test_login_attempts_are_rate_limited(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(auth_api, "_login_limit", lambda: "2/minute")
    limiter.reset()
    statuses = [
        client.post(
            "/api/v1/auth/login",
            json={"email": "x@meridian.example", "password": "whatever-pass-1"},
        ).status_code
        for _ in range(3)
    ]

    assert statuses[-1] == 429
