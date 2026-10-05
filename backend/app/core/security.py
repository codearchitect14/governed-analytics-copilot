"""Password hashing, access tokens and refresh token helpers.

- Passwords are hashed with Argon2id (argon2-cffi defaults).
- Access tokens are short lived JWTs (HS256) carrying sub, role, policy_version, jti.
- Refresh tokens are random values. Only their SHA-256 digest is stored.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.core.config import Settings

_hasher = PasswordHasher()
# Used to keep the response time of unknown accounts close to that of known ones.
_DUMMY_HASH = _hasher.hash("timing-equaliser-not-a-real-password")


class AuthError(Exception):
    """Authentication failed. The message is safe to return to the client."""


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def burn_password_time(password: str) -> None:
    """Run one verification so that unknown accounts take as long as known ones."""
    verify_password(_DUMMY_HASH, password)


def check_password_policy(password: str, minimum_length: int) -> None:
    if len(password) < minimum_length:
        raise ValueError(f"password must be at least {minimum_length} characters")


def new_refresh_token() -> str:
    return secrets.token_urlsafe(48)


def hash_refresh_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class AccessClaims:
    subject: str
    role: str
    policy_version: int
    jti: str
    expires_at: datetime


def utc_now() -> datetime:
    return datetime.now(UTC)


def issue_access_token(
    settings: Settings, *, user_id: str, role: str, policy_version: int, now: datetime | None = None
) -> tuple[str, AccessClaims]:
    issued = now or utc_now()
    expires = issued + timedelta(minutes=settings.access_token_minutes)
    jti = uuid.uuid4().hex
    payload: dict[str, Any] = {
        "sub": user_id,
        "role": role,
        "policy_version": policy_version,
        "jti": jti,
        "iat": int(issued.timestamp()),
        "exp": int(expires.timestamp()),
        "iss": settings.jwt_issuer,
    }
    token = jwt.encode(payload, settings.jwt_secret.get_secret_value(), algorithm="HS256")
    return token, AccessClaims(
        subject=user_id,
        role=role,
        policy_version=policy_version,
        jti=jti,
        expires_at=expires,
    )


def decode_access_token(settings: Settings, token: str) -> AccessClaims:
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret.get_secret_value(),
            algorithms=["HS256"],
            issuer=settings.jwt_issuer,
            options={"require": ["sub", "role", "policy_version", "jti", "exp", "iat", "iss"]},
        )
    except jwt.ExpiredSignatureError as error:
        raise AuthError("Access token has expired") from error
    except jwt.InvalidTokenError as error:
        raise AuthError("Invalid access token") from error
    return AccessClaims(
        subject=str(payload["sub"]),
        role=str(payload["role"]),
        policy_version=int(payload["policy_version"]),
        jti=str(payload["jti"]),
        expires_at=datetime.fromtimestamp(int(payload["exp"]), tz=UTC),
    )
