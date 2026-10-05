"""FastAPI dependencies: authenticated user and route level RBAC (layer 1)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import Engine

from app.audit.writer import AuditEvent, append_event
from app.auth.service import AuthService, CurrentUser, RequestContext
from app.core.config import Settings, get_settings
from app.core.security import AuthError
from app.db.engine import get_engine

bearer_scheme = HTTPBearer(auto_error=False)


def settings_dependency() -> Settings:
    return get_settings()


def engine_dependency(settings: Annotated[Settings, Depends(settings_dependency)]) -> Engine:
    return get_engine(settings)


def auth_service_dependency(
    engine: Annotated[Engine, Depends(engine_dependency)],
    settings: Annotated[Settings, Depends(settings_dependency)],
) -> AuthService:
    return AuthService(engine, settings)


def request_context(request: Request) -> RequestContext:
    forwarded = request.headers.get("x-forwarded-for")
    client_ip = (
        forwarded.split(",")[0].strip()
        if forwarded
        else (request.client.host if request.client else None)
    )
    request_id = request.scope.get("state", {}).get("request_id")
    return RequestContext(
        client_ip=client_ip,
        user_agent=request.headers.get("user-agent"),
        request_id=request_id,
    )


def current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    service: Annotated[AuthService, Depends(auth_service_dependency)],
) -> CurrentUser:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        return service.current_user(credentials.credentials)
    except AuthError as error:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(error),
            headers={"WWW-Authenticate": "Bearer"},
        ) from error


CurrentUserDep = Annotated[CurrentUser, Depends(current_user)]


def require_roles(*allowed: str) -> Callable[..., CurrentUser]:
    """Dependency factory. Denials are audited with the route and the required roles."""
    allowed_set = frozenset(allowed)

    def checker(
        user: CurrentUserDep,
        engine: Annotated[Engine, Depends(engine_dependency)],
        context: Annotated[RequestContext, Depends(request_context)],
        request: Request,
    ) -> CurrentUser:
        if user.role in allowed_set:
            return user
        with engine.begin() as connection:
            append_event(
                connection,
                AuditEvent(
                    event="access_denied",
                    decision="denied",
                    user_id=user.id,
                    role=user.role,
                    route=request.url.path,
                    denial_reason=f"requires one of: {', '.join(sorted(allowed_set))}",
                    client_ip=context.client_ip,
                    request_id=context.request_id,
                ),
            )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Your role does not allow this action",
        )

    return checker
