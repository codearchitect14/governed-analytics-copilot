"""Authentication endpoints: login, refresh, logout and the current user."""

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, EmailStr, Field

from app.auth.deps import (
    CurrentUserDep,
    auth_service_dependency,
    request_context,
    settings_dependency,
)
from app.auth.service import AuthService, CurrentUser, RequestContext, TokenPair
from app.core.config import Settings, get_settings
from app.core.ratelimit import limiter
from app.core.security import AuthError

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])
COOKIE_PATH = "/api/v1/auth"


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=256)


class UserOut(BaseModel):
    id: UUID
    email: str
    full_name: str
    role: str
    policy_version: int


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"  # noqa: S105 - OAuth token type, not a secret
    expires_at: datetime
    user: UserOut


def _user_out(user: CurrentUser) -> UserOut:
    return UserOut(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        role=user.role,
        policy_version=user.policy_version,
    )


def _set_refresh_cookie(response: Response, pair: TokenPair, settings: Settings) -> None:
    remaining = int((pair.refresh_expires_at - datetime.now(UTC)).total_seconds())
    response.set_cookie(
        key=settings.refresh_cookie_name,
        value=pair.refresh_token,
        max_age=max(remaining, 1),
        path=COOKIE_PATH,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="strict",
    )


def _respond(pair: TokenPair, response: Response, settings: Settings) -> TokenResponse:
    _set_refresh_cookie(response, pair, settings)
    response.headers["Cache-Control"] = "no-store"
    return TokenResponse(
        access_token=pair.access_token,
        expires_at=pair.access_expires_at,
        user=_user_out(pair.user),
    )


@router.post(
    "/login", response_model=TokenResponse, responses={401: {"description": "Invalid credentials"}}
)
@limiter.limit(lambda: _login_limit())
def login(
    request: Request,
    body: LoginRequest,
    response: Response,
    service: Annotated[AuthService, Depends(auth_service_dependency)],
    settings: Annotated[Settings, Depends(settings_dependency)],
    context: Annotated[RequestContext, Depends(request_context)],
) -> TokenResponse:
    try:
        pair = service.login(str(body.email), body.password, context)
    except AuthError as error:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(error)) from error
    return _respond(pair, response, settings)


@router.post(
    "/refresh", response_model=TokenResponse, responses={401: {"description": "Invalid token"}}
)
def refresh(
    response: Response,
    service: Annotated[AuthService, Depends(auth_service_dependency)],
    settings: Annotated[Settings, Depends(settings_dependency)],
    context: Annotated[RequestContext, Depends(request_context)],
    refresh_cookie: Annotated[str | None, Cookie(alias="refresh_token")] = None,
) -> TokenResponse:
    if not refresh_cookie:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token"
        )
    try:
        pair = service.refresh(refresh_cookie, context)
    except AuthError as error:
        response.delete_cookie(settings.refresh_cookie_name, path=COOKIE_PATH)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(error)) from error
    return _respond(pair, response, settings)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    response: Response,
    service: Annotated[AuthService, Depends(auth_service_dependency)],
    settings: Annotated[Settings, Depends(settings_dependency)],
    context: Annotated[RequestContext, Depends(request_context)],
    refresh_cookie: Annotated[str | None, Cookie(alias="refresh_token")] = None,
) -> Response:
    service.logout(refresh_cookie, context)
    response.delete_cookie(settings.refresh_cookie_name, path=COOKIE_PATH)
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.get("/me", response_model=UserOut)
def me(user: CurrentUserDep) -> UserOut:
    return _user_out(user)


def _login_limit() -> str:
    return get_settings().rate_limit_login
