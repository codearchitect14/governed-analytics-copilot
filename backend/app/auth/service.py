"""Authentication: login with lockout, refresh token rotation, logout and current user lookup.

Failures that must persist (failed login counters, lockouts, reuse revocations) are committed
before AuthError is raised, so they are not rolled back with the failed request.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import Engine, text
from sqlalchemy.engine import Connection

from app.audit.writer import AuditEvent, append_event
from app.core.config import Settings
from app.core.security import (
    AccessClaims,
    AuthError,
    burn_password_time,
    decode_access_token,
    hash_refresh_token,
    issue_access_token,
    new_refresh_token,
    verify_password,
)

GENERIC_LOGIN_ERROR = "Invalid email or password"
GENERIC_SESSION_ERROR = "Session is no longer valid. Sign in again."


@dataclass(frozen=True)
class CurrentUser:
    id: uuid.UUID
    email: str
    full_name: str
    role: str
    policy_version: int
    scopes: dict[str, Any]


@dataclass(frozen=True)
class TokenPair:
    access_token: str
    access_expires_at: datetime
    refresh_token: str
    refresh_expires_at: datetime
    user: CurrentUser


@dataclass(frozen=True)
class RequestContext:
    client_ip: str | None = None
    user_agent: str | None = None
    request_id: str | None = None


def _now() -> datetime:
    return datetime.now(UTC)


def _audit(
    connection: Connection,
    context: RequestContext,
    *,
    event: str,
    decision: str,
    user_id: uuid.UUID | None = None,
    role: str | None = None,
    denial_reason: str | None = None,
) -> None:
    append_event(
        connection,
        AuditEvent(
            event=event,
            decision=decision,  # type: ignore[arg-type]
            user_id=user_id,
            role=role,
            route="auth",
            denial_reason=denial_reason,
            client_ip=context.client_ip,
            request_id=context.request_id,
        ),
    )


class AuthService:
    def __init__(self, engine: Engine, settings: Settings) -> None:
        self._engine = engine
        self._settings = settings

    # ---- login ------------------------------------------------------------------------------

    def login(self, email: str, password: str, context: RequestContext) -> TokenPair:
        error: str | None = None
        result: TokenPair | None = None
        now = _now()
        with self._engine.begin() as connection:
            user = (
                connection.execute(
                    text(
                        """
                    SELECT u.id, u.email, u.full_name, u.password_hash, u.role, u.scopes,
                           u.is_active, u.failed_login_count, u.locked_until, rp.version AS policy_version
                    FROM app.users u
                    JOIN app.role_policies rp ON rp.role = u.role
                    WHERE lower(u.email) = lower(:email)
                    """
                    ),
                    {"email": email},
                )
                .mappings()
                .first()
            )

            if user is None:
                burn_password_time(password)
                _audit(
                    connection,
                    context,
                    event="login_failed",
                    decision="denied",
                    denial_reason="unknown account",
                )
                error = GENERIC_LOGIN_ERROR
            elif user["locked_until"] is not None and user["locked_until"] > now:
                _audit(
                    connection,
                    context,
                    event="login_blocked",
                    decision="denied",
                    user_id=user["id"],
                    role=user["role"],
                    denial_reason="account locked",
                )
                error = GENERIC_LOGIN_ERROR
            elif not user["is_active"]:
                _audit(
                    connection,
                    context,
                    event="login_blocked",
                    decision="denied",
                    user_id=user["id"],
                    role=user["role"],
                    denial_reason="account disabled",
                )
                error = GENERIC_LOGIN_ERROR
            elif not verify_password(str(user["password_hash"]), password):
                failures = int(user["failed_login_count"]) + 1
                locked_until = None
                if failures >= self._settings.lockout_threshold:
                    locked_until = now + timedelta(minutes=self._settings.lockout_minutes)
                    _audit(
                        connection,
                        context,
                        event="account_locked",
                        decision="denied",
                        user_id=user["id"],
                        role=user["role"],
                        denial_reason=f"{failures} failed attempts",
                    )
                connection.execute(
                    text(
                        """
                        UPDATE app.users SET failed_login_count = :failures, locked_until = :locked_until,
                            updated_at = now() WHERE id = :id
                        """
                    ),
                    {"failures": failures, "locked_until": locked_until, "id": user["id"]},
                )
                _audit(
                    connection,
                    context,
                    event="login_failed",
                    decision="denied",
                    user_id=user["id"],
                    role=user["role"],
                    denial_reason="wrong password",
                )
                error = GENERIC_LOGIN_ERROR
            else:
                connection.execute(
                    text(
                        """
                        UPDATE app.users SET failed_login_count = 0, locked_until = NULL,
                            updated_at = now() WHERE id = :id
                        """
                    ),
                    {"id": user["id"]},
                )
                _audit(
                    connection,
                    context,
                    event="login_succeeded",
                    decision="allowed",
                    user_id=user["id"],
                    role=user["role"],
                )
                result = self._issue_session(
                    connection, dict(user), family_id=uuid.uuid4(), context=context
                )

        if error is not None or result is None:
            raise AuthError(error or GENERIC_LOGIN_ERROR)
        return result

    # ---- refresh and logout -----------------------------------------------------------------

    def refresh(self, refresh_token: str, context: RequestContext) -> TokenPair:
        error: str | None = None
        result: TokenPair | None = None
        token_hash = hash_refresh_token(refresh_token)
        now = _now()
        with self._engine.begin() as connection:
            row = (
                connection.execute(
                    text(
                        """
                    SELECT rt.id, rt.user_id, rt.family_id, rt.used_at, rt.revoked_at, rt.expires_at,
                           u.email, u.full_name, u.role, u.scopes, u.is_active, rp.version AS policy_version
                    FROM app.refresh_tokens rt
                    JOIN app.users u ON u.id = rt.user_id
                    JOIN app.role_policies rp ON rp.role = u.role
                    WHERE rt.token_hash = :token_hash
                    FOR UPDATE OF rt
                    """
                    ),
                    {"token_hash": token_hash},
                )
                .mappings()
                .first()
            )

            if row is None:
                error = "Invalid refresh token"
            elif row["used_at"] is not None:
                # A rotated token was presented again: treat the whole family as compromised.
                connection.execute(
                    text(
                        """
                        UPDATE app.refresh_tokens SET revoked_at = :now
                        WHERE family_id = :family AND revoked_at IS NULL
                        """
                    ),
                    {"now": now, "family": row["family_id"]},
                )
                _audit(
                    connection,
                    context,
                    event="refresh_reuse_detected",
                    decision="denied",
                    user_id=row["user_id"],
                    role=row["role"],
                    denial_reason="rotated token reused",
                )
                error = "Invalid refresh token"
            elif row["revoked_at"] is not None or row["expires_at"] <= now or not row["is_active"]:
                error = "Invalid refresh token"
            else:
                user = {
                    "id": row["user_id"],
                    "email": row["email"],
                    "full_name": row["full_name"],
                    "role": row["role"],
                    "scopes": row["scopes"],
                    "policy_version": row["policy_version"],
                }
                result = self._issue_session(
                    connection,
                    user,
                    family_id=row["family_id"],
                    context=context,
                    rotated_from=row["id"],
                )

        if error is not None or result is None:
            raise AuthError(error or "Invalid refresh token")
        return result

    def logout(self, refresh_token: str | None, context: RequestContext) -> None:
        if not refresh_token:
            return
        token_hash = hash_refresh_token(refresh_token)
        with self._engine.begin() as connection:
            row = (
                connection.execute(
                    text(
                        """
                    SELECT rt.family_id, rt.user_id, u.role FROM app.refresh_tokens rt
                    JOIN app.users u ON u.id = rt.user_id WHERE rt.token_hash = :token_hash
                    """
                    ),
                    {"token_hash": token_hash},
                )
                .mappings()
                .first()
            )
            if row is None:
                return
            connection.execute(
                text(
                    """
                    UPDATE app.refresh_tokens SET revoked_at = :now
                    WHERE family_id = :family AND revoked_at IS NULL
                    """
                ),
                {"now": _now(), "family": row["family_id"]},
            )
            _audit(
                connection,
                context,
                event="logout",
                decision="info",
                user_id=row["user_id"],
                role=row["role"],
            )

    # ---- access tokens ----------------------------------------------------------------------

    def current_user(self, access_token: str) -> CurrentUser:
        claims: AccessClaims = decode_access_token(self._settings, access_token)
        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    text(
                        """
                    SELECT u.id, u.email, u.full_name, u.role, u.scopes, u.is_active,
                           rp.version AS policy_version
                    FROM app.users u JOIN app.role_policies rp ON rp.role = u.role
                    WHERE u.id = CAST(:id AS UUID)
                    """
                    ),
                    {"id": claims.subject},
                )
                .mappings()
                .first()
            )
        if row is None or not row["is_active"]:
            raise AuthError(GENERIC_SESSION_ERROR)
        if int(row["policy_version"]) != claims.policy_version or row["role"] != claims.role:
            # The role or its policy changed after this token was issued.
            raise AuthError(GENERIC_SESSION_ERROR)
        return CurrentUser(
            id=row["id"],
            email=str(row["email"]),
            full_name=str(row["full_name"]),
            role=str(row["role"]),
            policy_version=int(row["policy_version"]),
            scopes=dict(row["scopes"] or {}),
        )

    # ---- helpers ----------------------------------------------------------------------------

    def _issue_session(
        self,
        connection: Connection,
        user: dict[str, Any],
        *,
        family_id: uuid.UUID,
        context: RequestContext,
        rotated_from: uuid.UUID | None = None,
    ) -> TokenPair:
        now = _now()
        refresh_token = new_refresh_token()
        refresh_expires = now + timedelta(days=self._settings.refresh_token_days)
        new_id: uuid.UUID = connection.execute(
            text(
                """
                INSERT INTO app.refresh_tokens (user_id, family_id, token_hash, issued_at, expires_at,
                    user_agent, client_ip)
                VALUES (:user_id, :family_id, :token_hash, :issued_at, :expires_at, :user_agent, :client_ip)
                RETURNING id
                """
            ),
            {
                "user_id": user["id"],
                "family_id": family_id,
                "token_hash": hash_refresh_token(refresh_token),
                "issued_at": now,
                "expires_at": refresh_expires,
                "user_agent": context.user_agent,
                "client_ip": context.client_ip,
            },
        ).scalar_one()
        if rotated_from is not None:
            connection.execute(
                text(
                    "UPDATE app.refresh_tokens SET used_at = :now, replaced_by = :new_id WHERE id = :old_id"
                ),
                {"now": now, "new_id": new_id, "old_id": rotated_from},
            )

        access_token, claims = issue_access_token(
            self._settings,
            user_id=str(user["id"]),
            role=str(user["role"]),
            policy_version=int(user["policy_version"]),
            now=now,
        )
        current = CurrentUser(
            id=user["id"],
            email=str(user["email"]),
            full_name=str(user["full_name"]),
            role=str(user["role"]),
            policy_version=int(user["policy_version"]),
            scopes=dict(user["scopes"] or {}),
        )
        return TokenPair(
            access_token=access_token,
            access_expires_at=claims.expires_at,
            refresh_token=refresh_token,
            refresh_expires_at=refresh_expires,
            user=current,
        )
