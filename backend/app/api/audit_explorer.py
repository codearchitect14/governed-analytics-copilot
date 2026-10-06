"""Audit explorer for administrators: filtered, paginated listing and CSV export."""

import csv
import datetime as dt
import io
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy import Engine, text

from app.auth.deps import engine_dependency, require_roles
from app.auth.service import CurrentUser

router = APIRouter(prefix="/api/v1/admin/audit", tags=["admin"])
AdminUser = Annotated[CurrentUser, Depends(require_roles("admin"))]
EngineDep = Annotated[Engine, Depends(engine_dependency)]
COLUMNS = (
    "id",
    "ts",
    "event",
    "user_id",
    "role",
    "route",
    "decision",
    "denial_reason",
    "question",
    "provider",
    "model",
    "prompt_version",
    "tokens_in",
    "tokens_out",
    "total_ms",
    "row_count",
    "policy_hash",
    "final_sql",
    "is_synthetic",
)
FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def _filters(
    user_id: UUID | None,
    role: str | None,
    route: str | None,
    decision: str | None,
    date_from: dt.date | None,
    date_to: dt.date | None,
    q: str | None,
) -> tuple[str, dict[str, Any]]:
    clauses = ["TRUE"]
    params: dict[str, Any] = {}
    if user_id:
        clauses.append("user_id = CAST(:user_id AS UUID)")
        params["user_id"] = str(user_id)
    if role:
        clauses.append("role = :role")
        params["role"] = role
    if route:
        clauses.append("route = :route")
        params["route"] = route
    if decision:
        clauses.append("decision = :decision")
        params["decision"] = decision
    if date_from:
        clauses.append("ts >= CAST(:date_from AS TIMESTAMPTZ)")
        params["date_from"] = date_from.isoformat()
    if date_to:
        clauses.append("ts < CAST(:date_to AS TIMESTAMPTZ) + interval '1 day'")
        params["date_to"] = date_to.isoformat()
    if q:
        clauses.append("(question ILIKE :q OR denial_reason ILIKE :q)")
        params["q"] = f"%{q}%"
    return " AND ".join(clauses), params


def _cell(value: Any) -> str:
    text_value = "" if value is None else str(value)
    if text_value.startswith(FORMULA_PREFIXES):
        # Stop spreadsheet applications from running a formula found in logged text
        return "'" + text_value
    return text_value


@router.get("")
def list_audit(
    _admin: AdminUser,
    engine: EngineDep,
    user_id: Annotated[UUID | None, Query()] = None,
    role: Annotated[str | None, Query(max_length=64)] = None,
    route: Annotated[str | None, Query(max_length=32)] = None,
    decision: Annotated[str | None, Query(pattern="^(allowed|denied|clarify|error|info)$")] = None,
    date_from: Annotated[dt.date | None, Query()] = None,
    date_to: Annotated[dt.date | None, Query()] = None,
    q: Annotated[str | None, Query(max_length=200)] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    format: Annotated[str, Query(pattern="^(json|csv)$")] = "json",
) -> Any:
    where, params = _filters(user_id, role, route, decision, date_from, date_to, q)
    if format == "csv":
        params_all = {**params}
        with engine.connect() as connection:
            rows = connection.execute(
                text(
                    f"SELECT {', '.join(COLUMNS)} FROM app.audit_log WHERE {where} ORDER BY id DESC LIMIT 10000"
                ),
                params_all,
            ).mappings()
            buffer = io.StringIO()
            writer = csv.writer(buffer)
            writer.writerow(COLUMNS)
            for row in rows:
                writer.writerow([_cell(row[column]) for column in COLUMNS])
        return Response(
            content=buffer.getvalue(),
            media_type="text/csv",
            headers={"Content-Disposition": 'attachment; filename="audit-log.csv"'},
        )
    with engine.connect() as connection:
        total: int = connection.execute(
            text(f"SELECT count(*) FROM app.audit_log WHERE {where}"), params
        ).scalar_one()
        rows = connection.execute(
            text(
                f"SELECT {', '.join(COLUMNS)} FROM app.audit_log WHERE {where} "
                "ORDER BY id DESC LIMIT :limit OFFSET :offset"
            ),
            {**params, "limit": limit, "offset": offset},
        ).mappings()
        items = [
            {
                key: (
                    value.isoformat()
                    if isinstance(value, dt.datetime)
                    else (str(value) if isinstance(value, UUID) else value)
                )
                for key, value in row.items()
            }
            for row in rows
        ]
    return {"total": int(total), "limit": limit, "offset": offset, "items": items}
