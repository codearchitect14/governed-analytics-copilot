"""Seed roles, role policies and demo users. Idempotent.

Usage (from the backend directory, after migrations):
    uv run --package governed-analytics-backend python -m app.db.seed

Demo accounts are created only in the local and test environments. Their password comes from
DEMO_USER_PASSWORD. The documented demo password is used only when that variable is not set.
"""

from __future__ import annotations

import json
import sys
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection

from app.core.config import Settings, get_settings
from app.core.security import check_password_policy, hash_password
from app.db.engine import get_engine
from app.policy.definitions import DEMO_USERS, ROLES, RoleDefinition

DOCUMENTED_DEMO_PASSWORD = "DemoOnly-Meridian-2026"  # noqa: S105 - documented local demo value
DEMO_ENVIRONMENTS = frozenset({"local", "test"})


def _policy_document(role: RoleDefinition) -> dict[str, Any]:
    return dict(role.policy)


def seed_roles(connection: Connection) -> dict[str, str]:
    """Insert or update roles. Returns the action taken per role."""
    actions: dict[str, str] = {}
    for role in ROLES:
        connection.execute(
            text(
                """
                INSERT INTO app.roles (name, description) VALUES (:name, :description)
                ON CONFLICT (name) DO UPDATE SET description = EXCLUDED.description
                """
            ),
            {"name": role.name, "description": role.description},
        )
        document = _policy_document(role)
        current = connection.execute(
            text("SELECT row_to_json(p)::jsonb AS doc FROM app.role_policies p WHERE role = :name"),
            {"name": role.name},
        ).scalar()
        stored = _comparable(current) if current is not None else None
        wanted = _comparable(document)
        params = {
            "role": role.name,
            "allowed_tables": list(document["allowed_tables"]),
            "allowed_columns": json.dumps(document.get("allowed_columns", {})),
            "row_filters": json.dumps(document["row_filters"]),
            "masked_columns": json.dumps(document["masked_columns"]),
            "max_rows": int(document["max_rows"]),
            "allow_sql_fallback": bool(document["allow_sql_fallback"]),
        }
        if current is None:
            connection.execute(
                text(
                    """
                    INSERT INTO app.role_policies (role, allowed_tables, allowed_columns, row_filters,
                        masked_columns, max_rows, allow_sql_fallback)
                    VALUES (:role, :allowed_tables, CAST(:allowed_columns AS JSONB),
                        CAST(:row_filters AS JSONB), CAST(:masked_columns AS JSONB),
                        :max_rows, :allow_sql_fallback)
                    """
                ),
                params,
            )
            actions[role.name] = "created"
        elif stored != wanted:
            connection.execute(
                text(
                    """
                    UPDATE app.role_policies SET allowed_tables = :allowed_tables,
                        allowed_columns = CAST(:allowed_columns AS JSONB),
                        row_filters = CAST(:row_filters AS JSONB),
                        masked_columns = CAST(:masked_columns AS JSONB),
                        max_rows = :max_rows, allow_sql_fallback = :allow_sql_fallback,
                        version = version + 1, updated_at = now()
                    WHERE role = :role
                    """
                ),
                params,
            )
            actions[role.name] = "updated"
        else:
            actions[role.name] = "unchanged"
    return actions


def _comparable(document: Any) -> dict[str, Any]:
    """Only policy content is compared. Version and timestamps are excluded."""
    if isinstance(document, str):
        document = json.loads(document)
    keys = (
        "allowed_tables",
        "allowed_columns",
        "row_filters",
        "masked_columns",
        "max_rows",
        "allow_sql_fallback",
    )
    result: dict[str, Any] = {}
    for key in keys:
        value = document.get(
            key, {} if key in {"allowed_columns", "row_filters", "masked_columns"} else None
        )
        if key == "allowed_tables":
            value = sorted(value or [])
        result[key] = value
    normalized: dict[str, Any] = json.loads(json.dumps(result, sort_keys=True, default=str))
    return normalized


def seed_demo_users(connection: Connection, password: str) -> dict[str, str]:
    check_password_policy(password, minimum_length=12)
    password_hash = hash_password(password)
    actions: dict[str, str] = {}
    for user in DEMO_USERS:
        exists = connection.execute(
            text("SELECT 1 FROM app.users WHERE lower(email) = lower(:email)"),
            {"email": user.email},
        ).first()
        if exists is not None:
            actions[user.email] = "exists"
            continue
        connection.execute(
            text(
                """
                INSERT INTO app.users (email, full_name, password_hash, role, scopes)
                VALUES (:email, :full_name, :password_hash, :role, CAST(:scopes AS JSONB))
                """
            ),
            {
                "email": user.email,
                "full_name": user.full_name,
                "password_hash": password_hash,
                "role": user.role,
                "scopes": json.dumps(user.scopes),
            },
        )
        actions[user.email] = "created"
    return actions


def run_seed(settings: Settings) -> dict[str, Any]:
    if settings.app_env not in DEMO_ENVIRONMENTS:
        raise SystemExit(f"Demo users are not seeded in the {settings.app_env} environment.")
    configured = (
        settings.demo_user_password.get_secret_value() if settings.demo_user_password else ""
    )
    password = configured or DOCUMENTED_DEMO_PASSWORD
    engine = get_engine(settings)
    with engine.begin() as connection:
        roles = seed_roles(connection)
        users = seed_demo_users(connection, password)
    return {"roles": roles, "users": users}


def main() -> int:
    result = run_seed(get_settings())
    for name, action in result["roles"].items():
        print(f"role {name:<18} {action}")
    for email, action in result["users"].items():
        print(f"user {email:<36} {action}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
