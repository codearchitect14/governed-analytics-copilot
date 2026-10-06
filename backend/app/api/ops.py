"""Operations endpoints for administrators: usage, latency, failures, budgets and evaluation runs."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy import Engine

from app.auth.deps import engine_dependency, require_roles
from app.auth.service import CurrentUser
from app.core.ratelimit import limiter
from app.ops import analytics
from app.pipeline.services import get_pipeline

router = APIRouter(prefix="/api/v1/admin/ops", tags=["operations"])
AdminUser = Annotated[CurrentUser, Depends(require_roles("admin"))]
EngineDep = Annotated[Engine, Depends(engine_dependency)]


@router.get("/summary")
@limiter.limit("60/minute")
def ops_summary(
    request: Request,
    response: Response,
    _admin: AdminUser,
    engine: EngineDep,
    days: Annotated[int, Query(ge=1, le=90)] = 30,
) -> dict[str, Any]:
    return analytics.summary(engine, days, get_pipeline().services.gateway)


@router.get("/evals")
def ops_evals(_admin: AdminUser, engine: EngineDep) -> dict[str, Any]:
    runs = analytics.evaluation_runs(engine)
    note = None if runs else "Evaluation runs appear here after the Phase 10 harness has run."
    return {"runs": runs, "note": note}
