"""FastAPI application factory."""

import secrets

import structlog
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app import __version__
from app.api import admin, audit_explorer, auth, chat, dashboard, health, ops, public, workspace
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.core.metrics import REGISTRY, MetricsMiddleware
from app.core.middleware import RequestIdMiddleware
from app.core.ratelimit import limiter
from app.core.security_headers import add_security_headers

logger = structlog.get_logger(__name__)


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)

    app = FastAPI(
        title="Meridian Data Copilot API",
        version=__version__,
        openapi_url="/api/v1/openapi.json",
        docs_url="/docs",
        redoc_url=None,
    )
    app.state.limiter = limiter
    app.add_exception_handler(
        RateLimitExceeded,
        _rate_limit_exceeded_handler,  # type: ignore[arg-type]
    )

    app.add_middleware(MetricsMiddleware, routes=app.routes)
    app.add_middleware(RequestIdMiddleware)
    app.middleware("http")(add_security_headers)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
        expose_headers=["X-Request-ID"],
        max_age=600,
    )

    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(admin.router)
    app.include_router(chat.router)
    app.include_router(dashboard.router)
    app.include_router(ops.router)
    app.include_router(public.router)
    app.include_router(workspace.router)
    app.include_router(audit_explorer.router)

    @app.get("/metrics", include_in_schema=False)
    def metrics(request: Request) -> PlainTextResponse:
        if settings.metrics_token is None:
            raise HTTPException(status_code=404)
        expected = f"Bearer {settings.metrics_token.get_secret_value()}"
        if not secrets.compare_digest(request.headers.get("authorization", ""), expected):
            raise HTTPException(status_code=401)
        return PlainTextResponse(REGISTRY.render(), media_type="text/plain; version=0.0.4")

    @app.exception_handler(Exception)
    async def unhandled_error(request: Request, exc: Exception) -> JSONResponse:
        request_id = request.scope.get("state", {}).get("request_id")
        logger.error("unhandled_exception", error_type=type(exc).__name__, exc_info=exc)
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error", "request_id": request_id},
        )

    return app


app = create_app()
