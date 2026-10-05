"""FastAPI application factory."""

import structlog
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app import __version__
from app.api import health
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.core.middleware import RequestIdMiddleware

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
    app.add_middleware(RequestIdMiddleware)
    app.include_router(health.router)

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
