"""Policy engine: turns a role policy and a user's scopes into an effective, hashed policy.

Layer 1 (route RBAC) is implemented as FastAPI dependencies in app.auth.deps.
Layer 2 (this module) decides which tables a user may query, which rows, which columns are
masked, and how many rows may be returned. The policy_hash identifies the exact policy that
applied to a request. It is stored in every audit row and in every cache key.

Fail closed: a row filter whose scope is missing for the user matches no rows.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

ANALYTICS_SCHEMA = "analytics"


class PolicyDenied(Exception):
    """A requested table or column is outside the user's policy."""

    def __init__(self, reason: str, tables: Iterable[str] = ()) -> None:
        super().__init__(reason)
        self.reason = reason
        self.tables = tuple(tables)


@dataclass(frozen=True)
class RowFilter:
    table: str
    column: str
    values: tuple[str, ...]  # an empty tuple means no row matches

    def is_deny_all(self) -> bool:
        return not self.values


@dataclass(frozen=True)
class EffectivePolicy:
    role: str
    policy_version: int
    allowed_tables: frozenset[str]
    row_filters: tuple[RowFilter, ...]
    masked_columns: Mapping[str, frozenset[str]]
    max_rows: int
    allow_sql_fallback: bool
    allowed_columns: Mapping[str, frozenset[str]] = field(default_factory=dict)

    @property
    def policy_hash(self) -> str:
        """Stable digest of everything that changes what a user can see."""
        material = {
            "role": self.role,
            "policy_version": self.policy_version,
            "allowed_tables": sorted(self.allowed_tables),
            "allowed_columns": {k: sorted(v) for k, v in sorted(self.allowed_columns.items())},
            "row_filters": [
                {"table": f.table, "column": f.column, "values": sorted(f.values)}
                for f in sorted(self.row_filters, key=lambda item: (item.table, item.column))
            ],
            "masked_columns": {k: sorted(v) for k, v in sorted(self.masked_columns.items())},
            "max_rows": self.max_rows,
            "allow_sql_fallback": self.allow_sql_fallback,
        }
        encoded = json.dumps(material, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    def check_tables(self, tables: Iterable[str]) -> None:
        requested = tuple(dict.fromkeys(tables))
        forbidden = [table for table in requested if table not in self.allowed_tables]
        if forbidden:
            raise PolicyDenied(
                f"Your role cannot query: {', '.join(forbidden)}",
                tables=forbidden,
            )

    def filters_for(self, table: str) -> tuple[RowFilter, ...]:
        return tuple(item for item in self.row_filters if item.table == table)

    def is_masked(self, table: str, column: str) -> bool:
        return column in self.masked_columns.get(table, frozenset())


def _scope_values(scopes: Mapping[str, Any], scope_name: str) -> tuple[str, ...]:
    raw = scopes.get(scope_name)
    if raw is None:
        return ()
    if isinstance(raw, str):
        return (raw,) if raw.strip() else ()
    if isinstance(raw, (list, tuple)):
        return tuple(str(item) for item in raw if str(item).strip())
    return ()


def build_effective_policy(
    *,
    role: str,
    policy_version: int,
    policy: Mapping[str, Any],
    scopes: Mapping[str, Any],
) -> EffectivePolicy:
    """Combine the stored role policy with one user's scopes.

    `policy` is a row of app.role_policies. Row filter templates have the shape
    {"analytics.fct_orders": [{"column": "customer_state", "scope": "regions"}]}.
    """
    row_filters: list[RowFilter] = []
    templates: Mapping[str, Any] = policy.get("row_filters") or {}
    for table, rules in templates.items():
        for rule in rules:
            values = _scope_values(scopes, str(rule["scope"]))
            row_filters.append(RowFilter(table=table, column=str(rule["column"]), values=values))

    masked: dict[str, frozenset[str]] = {
        table: frozenset(columns) for table, columns in (policy.get("masked_columns") or {}).items()
    }
    allowed_columns: dict[str, frozenset[str]] = {
        table: frozenset(columns)
        for table, columns in (policy.get("allowed_columns") or {}).items()
    }
    return EffectivePolicy(
        role=role,
        policy_version=policy_version,
        allowed_tables=frozenset(policy.get("allowed_tables") or ()),
        row_filters=tuple(row_filters),
        masked_columns=masked,
        max_rows=int(policy["max_rows"]),
        allow_sql_fallback=bool(policy["allow_sql_fallback"]),
        allowed_columns=allowed_columns,
    )
