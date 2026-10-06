"""Business dashboard endpoints. Every response is policy filtered and cached per user policy."""

import datetime as dt
from collections.abc import Callable
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status

from app.auth.deps import CurrentUserDep
from app.auth.service import CurrentUser
from app.core.ratelimit import limiter
from app.dashboard import service as svc
from app.dashboard.queries import FilterError, Filters
from app.pipeline.services import get_pipeline
from app.policy.engine import EffectivePolicy
from app.policy.loader import load_effective_policy

router = APIRouter(prefix="/api/v1/dashboard", tags=["dashboard"])
Compare = Literal["none", "previous", "yoy"]


def _build_filters(
    start: dt.date | None,
    end: dt.date | None,
    state: str | None,
    category: str | None,
    compare: Compare,
    as_of: dt.date,
) -> Filters:
    default = svc.default_filters(as_of)
    try:
        return Filters(
            start=start or default.start,
            end=end or default.end,
            state=state.upper() if state else None,
            category=category.lower() if category else None,
            compare=compare,
        )
    except FilterError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)
        ) from error


def _respond(
    request: Request,
    response: Response,
    name: str,
    user: CurrentUser,
    filters: Filters,
    build: Callable[[EffectivePolicy, dt.date], dict[str, Any]],
) -> dict[str, Any]:
    pipeline = get_pipeline()
    as_of = pipeline.data_as_of()
    policy = load_effective_policy(pipeline.services.app_engine, user.id)
    key_parts = (name, filters.start, filters.end, filters.state, filters.category, filters.compare)
    try:
        entry = svc.cached(key_parts, user, policy, lambda: build(policy, as_of))
    except svc.SectionUnavailable as error:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Your role cannot view this dashboard"
        ) from error
    response.headers["ETag"] = f'"{entry.etag}"'
    response.headers["Cache-Control"] = "private, max-age=300"
    if request.headers.get("if-none-match") == f'"{entry.etag}"':
        response.status_code = status.HTTP_304_NOT_MODIFIED
        return {}
    return entry.body


QueryParams = dict[str, Any]


def _params(
    start: Annotated[dt.date | None, Query()] = None,
    end: Annotated[dt.date | None, Query()] = None,
    state: Annotated[str | None, Query(min_length=2, max_length=2)] = None,
    category: Annotated[str | None, Query(max_length=60)] = None,
    compare: Annotated[Compare, Query()] = "none",
) -> QueryParams:
    return {"start": start, "end": end, "state": state, "category": category, "compare": compare}


ParamsDep = Annotated[QueryParams, Depends(_params)]


def _service_for(policy: EffectivePolicy, as_of: dt.date) -> svc.DashboardService:
    return svc.DashboardService(get_pipeline().services, policy, as_of)


@router.get("/overview")
@limiter.limit("60/minute")
def overview(
    request: Request, response: Response, user: CurrentUserDep, params: ParamsDep
) -> dict[str, Any]:
    filters = _build_filters(
        params["start"],
        params["end"],
        params["state"],
        params["category"],
        params["compare"],
        get_pipeline().data_as_of(),
    )
    return _respond(
        request,
        response,
        "overview",
        user,
        filters,
        lambda policy, as_of: _service_for(policy, as_of).overview(filters),
    )


@router.get("/sales")
@limiter.limit("60/minute")
def sales(
    request: Request, response: Response, user: CurrentUserDep, params: ParamsDep
) -> dict[str, Any]:
    filters = _build_filters(
        params["start"],
        params["end"],
        params["state"],
        params["category"],
        params["compare"],
        get_pipeline().data_as_of(),
    )
    return _respond(
        request,
        response,
        "sales",
        user,
        filters,
        lambda policy, as_of: _service_for(policy, as_of).sales(filters),
    )


@router.get("/customers")
@limiter.limit("60/minute")
def customers(
    request: Request, response: Response, user: CurrentUserDep, params: ParamsDep
) -> dict[str, Any]:
    filters = _build_filters(
        params["start"],
        params["end"],
        params["state"],
        params["category"],
        params["compare"],
        get_pipeline().data_as_of(),
    )
    return _respond(
        request,
        response,
        "customers",
        user,
        filters,
        lambda policy, as_of: _service_for(policy, as_of).customers(filters),
    )


@router.get("/logistics")
@limiter.limit("60/minute")
def logistics(
    request: Request, response: Response, user: CurrentUserDep, params: ParamsDep
) -> dict[str, Any]:
    filters = _build_filters(
        params["start"],
        params["end"],
        params["state"],
        params["category"],
        params["compare"],
        get_pipeline().data_as_of(),
    )
    return _respond(
        request,
        response,
        "logistics",
        user,
        filters,
        lambda policy, as_of: _service_for(policy, as_of).logistics(filters),
    )


@router.get("/sellers")
@limiter.limit("60/minute")
def sellers(
    request: Request, response: Response, user: CurrentUserDep, params: ParamsDep
) -> dict[str, Any]:
    filters = _build_filters(
        params["start"],
        params["end"],
        params["state"],
        params["category"],
        params["compare"],
        get_pipeline().data_as_of(),
    )
    return _respond(
        request,
        response,
        "sellers",
        user,
        filters,
        lambda policy, as_of: _service_for(policy, as_of).sellers(filters),
    )
