"""Liveness and readiness probes."""

from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel

from app import __version__
from app.core.config import Settings, get_settings
from app.db.readiness import check_database

router = APIRouter(prefix="/api/v1", tags=["probes"])


class HealthResponse(BaseModel):
    status: str
    version: str


class ReadyResponse(BaseModel):
    status: str
    checks: dict[str, str]


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Liveness: the process is running."""
    return HealthResponse(status="ok", version=__version__)


@router.get("/ready", response_model=ReadyResponse, responses={503: {"model": ReadyResponse}})
def ready(
    response: Response,
    settings: Annotated[Settings, Depends(get_settings)],
) -> ReadyResponse:
    """Readiness: dependencies needed to serve traffic are reachable."""
    database_ok = check_database(settings)
    if not database_ok:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return ReadyResponse(
        status="ok" if database_ok else "unavailable",
        checks={"database": "ok" if database_ok else "unreachable"},
    )
