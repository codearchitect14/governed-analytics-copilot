"""Administration endpoints. Every route requires the admin role (route level RBAC)."""

from __future__ import annotations

import json
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import Engine, text

from app.audit.verify import ChainReport, verify_chain
from app.auth.deps import engine_dependency, require_roles
from app.auth.service import CurrentUser
from app.core.config import Settings, get_settings
from app.core.security import check_password_policy, hash_password
from app.pipeline.services import get_pipeline, read_llm_mode

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])
AdminUser = Annotated[CurrentUser, Depends(require_roles("admin"))]
EngineDep = Annotated[Engine, Depends(engine_dependency)]


class UserSummary(BaseModel):
    id: UUID
    email: str
    full_name: str
    role: str
    scopes: dict[str, Any]
    is_active: bool
    locked_until: str | None


class CreateUserRequest(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=1, max_length=256)
    role: str = Field(min_length=1, max_length=64)
    scopes: dict[str, Any] = Field(default_factory=dict)


class UpdateUserRequest(BaseModel):
    role: str | None = Field(default=None, min_length=1, max_length=64)
    scopes: dict[str, Any] | None = None
    is_active: bool | None = None
    unlock: bool = False


class RoleSummary(BaseModel):
    name: str
    description: str
    policy_version: int
    allowed_tables: list[str]
    max_rows: int
    allow_sql_fallback: bool


class ChainReportOut(BaseModel):
    ok: bool
    rows_checked: int
    first_invalid_id: int | None
    reason: str | None


def _user_row(row: Any) -> UserSummary:
    return UserSummary(
        id=row["id"],
        email=str(row["email"]),
        full_name=str(row["full_name"]),
        role=str(row["role"]),
        scopes=dict(row["scopes"] or {}),
        is_active=bool(row["is_active"]),
        locked_until=row["locked_until"].isoformat() if row["locked_until"] else None,
    )


@router.get("/users", response_model=list[UserSummary])
def list_users(
    _admin: AdminUser,
    engine: EngineDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[UserSummary]:
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                """
                SELECT id, email, full_name, role, scopes, is_active, locked_until
                FROM app.users ORDER BY lower(email) LIMIT :limit OFFSET :offset
                """
            ),
            {"limit": limit, "offset": offset},
        ).mappings()
        return [_user_row(row) for row in rows]


@router.post("/users", response_model=UserSummary, status_code=status.HTTP_201_CREATED)
def create_user(
    body: CreateUserRequest,
    _admin: AdminUser,
    engine: EngineDep,
    settings: Annotated[Settings, Depends(get_settings)],
) -> UserSummary:
    try:
        check_password_policy(body.password, settings.password_min_length)
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)
        ) from error
    with engine.begin() as connection:
        role_exists = connection.execute(
            text("SELECT 1 FROM app.roles WHERE name = :role"), {"role": body.role}
        ).first()
        if role_exists is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Unknown role"
            )
        duplicate = connection.execute(
            text("SELECT 1 FROM app.users WHERE lower(email) = lower(:email)"),
            {"email": body.email},
        ).first()
        if duplicate is not None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already exists")
        row = (
            connection.execute(
                text(
                    """
                INSERT INTO app.users (email, full_name, password_hash, role, scopes)
                VALUES (:email, :full_name, :password_hash, :role, CAST(:scopes AS JSONB))
                RETURNING id, email, full_name, role, scopes, is_active, locked_until
                """
                ),
                {
                    "email": str(body.email),
                    "full_name": body.full_name,
                    "password_hash": hash_password(body.password),
                    "role": body.role,
                    "scopes": json.dumps(body.scopes),
                },
            )
            .mappings()
            .one()
        )
    return _user_row(row)


@router.patch("/users/{user_id}", response_model=UserSummary)
def update_user(
    user_id: UUID,
    body: UpdateUserRequest,
    _admin: AdminUser,
    engine: EngineDep,
) -> UserSummary:
    assignments: list[str] = []
    params: dict[str, Any] = {"id": user_id}
    if body.role is not None:
        assignments.append("role = :role")
        params["role"] = body.role
    if body.scopes is not None:
        assignments.append("scopes = CAST(:scopes AS JSONB)")
        params["scopes"] = json.dumps(body.scopes)
    if body.is_active is not None:
        assignments.append("is_active = :is_active")
        params["is_active"] = body.is_active
    if body.unlock:
        assignments.append("locked_until = NULL, failed_login_count = 0")
    if not assignments:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Nothing to update"
        )
    assignments.append("updated_at = now()")
    with engine.begin() as connection:
        set_clause = ", ".join(assignments)
        row = (
            connection.execute(
                text(
                    f"""
                UPDATE app.users SET {set_clause} WHERE id = :id
                RETURNING id, email, full_name, role, scopes, is_active, locked_until
                """
                ),
                params,
            )
            .mappings()
            .first()
        )
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return _user_row(row)


@router.get("/roles", response_model=list[RoleSummary])
def list_roles(_admin: AdminUser, engine: EngineDep) -> list[RoleSummary]:
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                """
                SELECT r.name, r.description, rp.version, rp.allowed_tables, rp.max_rows,
                       rp.allow_sql_fallback
                FROM app.roles r JOIN app.role_policies rp ON rp.role = r.name ORDER BY r.name
                """
            )
        ).mappings()
        return [
            RoleSummary(
                name=str(row["name"]),
                description=str(row["description"]),
                policy_version=int(row["version"]),
                allowed_tables=list(row["allowed_tables"] or []),
                max_rows=int(row["max_rows"]),
                allow_sql_fallback=bool(row["allow_sql_fallback"]),
            )
            for row in rows
        ]


@router.get("/audit/verify", response_model=ChainReportOut)
def verify_audit(_admin: AdminUser, engine: EngineDep) -> ChainReportOut:
    with engine.connect() as connection:
        report: ChainReport = verify_chain(connection)
    return ChainReportOut(
        ok=report.ok,
        rows_checked=report.rows_checked,
        first_invalid_id=report.first_invalid_id,
        reason=report.reason,
    )


class LlmModeRequest(BaseModel):
    mode: Literal["auto", "groq_only", "gemini_only"]


class LlmStatusOut(BaseModel):
    mode: str
    providers: list[dict[str, object]]


@router.get("/llm", response_model=LlmStatusOut)
def llm_status(_admin: AdminUser, engine: EngineDep) -> LlmStatusOut:
    gateway = get_pipeline().services.gateway
    providers = gateway.provider_status() if gateway is not None else []
    return LlmStatusOut(mode=read_llm_mode(engine), providers=providers)


@router.put("/llm/mode", response_model=LlmStatusOut)
def set_llm_mode(body: LlmModeRequest, _admin: AdminUser, engine: EngineDep) -> LlmStatusOut:
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO app.llm_settings (key, value, updated_at) VALUES ('llm_mode', :mode, now())
                ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now()
                """
            ),
            {"mode": body.mode},
        )
    gateway = get_pipeline().services.gateway
    providers = gateway.provider_status() if gateway is not None else []
    return LlmStatusOut(mode=read_llm_mode(engine), providers=providers)
