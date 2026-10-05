"""Load a user's effective policy from the database for every request."""

from __future__ import annotations

import uuid

from sqlalchemy import Engine, text

from app.policy.engine import EffectivePolicy, build_effective_policy


class UnknownUser(Exception):
    """The user or the role policy no longer exists or is inactive."""


def load_effective_policy(engine: Engine, user_id: uuid.UUID) -> EffectivePolicy:
    with engine.connect() as connection:
        row = (
            connection.execute(
                text(
                    """
                SELECT u.role, u.scopes, u.is_active, rp.version, rp.allowed_tables, rp.allowed_columns,
                       rp.row_filters, rp.masked_columns, rp.max_rows, rp.allow_sql_fallback
                FROM app.users u JOIN app.role_policies rp ON rp.role = u.role
                WHERE u.id = CAST(:id AS UUID)
                """
                ),
                {"id": str(user_id)},
            )
            .mappings()
            .first()
        )
    if row is None or not row["is_active"]:
        raise UnknownUser("user is not active")
    policy = {
        "allowed_tables": list(row["allowed_tables"] or []),
        "allowed_columns": row["allowed_columns"] or {},
        "row_filters": row["row_filters"] or {},
        "masked_columns": {
            table: list(cols) for table, cols in (row["masked_columns"] or {}).items()
        },
        "max_rows": row["max_rows"],
        "allow_sql_fallback": row["allow_sql_fallback"],
    }
    return build_effective_policy(
        role=str(row["role"]),
        policy_version=int(row["version"]),
        policy=policy,
        scopes=dict(row["scopes"] or {}),
    )
