"""SQL validation and policy rewrite (layers 3 of the authorization model).

validate_and_rewrite() accepts one PostgreSQL SELECT or WITH statement that reads only
analytics tables allowed by the user's policy, then rewrites every analytics table reference:

    analytics.fct_orders AS o
        ->  (SELECT <columns, masked columns hashed> FROM analytics.fct_orders
             WHERE customer_state IN ('SP', 'RJ')) AS o

Values in the predicates are built as sqlglot literals, never by string concatenation.
The rewritten SQL is parsed again before it is returned.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError, SqlglotError, TokenError

from app.policy.engine import ANALYTICS_SCHEMA, EffectivePolicy, PolicyDenied, RowFilter

DIALECT = "postgres"
MAX_SQL_LENGTH = 8000
FORBIDDEN_FUNCTIONS = frozenset(
    {
        "pg_sleep",
        "pg_sleep_for",
        "pg_sleep_until",
        "pg_read_file",
        "pg_read_binary_file",
        "pg_ls_dir",
        "pg_stat_file",
        "dblink",
        "dblink_exec",
        "lo_import",
        "lo_export",
        "set_config",
        "generate_series",
        "current_setting",
        "pg_terminate_backend",
        "pg_cancel_backend",
    }
)
FORBIDDEN_TEXT_FRAGMENTS = ("--", "/*", "*/", ";")


class SqlRejected(Exception):
    """The SQL failed validation. The reason is safe to show to the user."""

    def __init__(self, reason: str, rule: str) -> None:
        super().__init__(reason)
        self.reason = reason
        self.rule = rule


@dataclass(frozen=True)
class RewriteResult:
    sql: str
    tables: tuple[str, ...]
    filtered_tables: tuple[str, ...]
    masked: tuple[str, ...]
    notes: list[str] = field(default_factory=list)


def _lower_name(node: exp.Expression) -> str:
    return node.name.lower()


def _analytics_table(table: exp.Table) -> str | None:
    if table.args.get("db") is None or table.db.lower() != ANALYTICS_SCHEMA:
        return None
    catalog = table.catalog.lower() if table.catalog else ""
    if catalog not in ("", "copilot", "governed"):
        return None
    return f"{ANALYTICS_SCHEMA}.{table.name.lower()}"


def parse_single_statement(sql: str) -> exp.Expression:
    text = sql.strip()
    if not text:
        raise SqlRejected("The generated query is empty.", "empty")
    if len(text) > MAX_SQL_LENGTH:
        raise SqlRejected("The generated query is too long.", "length")
    for fragment in FORBIDDEN_TEXT_FRAGMENTS:
        if fragment in text:
            raise SqlRejected("Comments and multiple statements are not allowed.", "text")
    try:
        statements = [item for item in sqlglot.parse(text, read=DIALECT) if item is not None]
    except (ParseError, TokenError, SqlglotError) as error:
        raise SqlRejected("The generated query is not valid PostgreSQL.", "parse") from error
    if len(statements) != 1:
        raise SqlRejected("Exactly one statement is allowed.", "statement_count")
    statement = statements[0]
    if not isinstance(statement, (exp.Select, exp.Union)):
        raise SqlRejected("Only SELECT and WITH queries are allowed.", "statement_type")
    return statement


def _cte_names(statement: exp.Expression) -> set[str]:
    return {cte.alias_or_name.lower() for cte in statement.find_all(exp.CTE)}


def validate(statement: exp.Expression, policy: EffectivePolicy) -> tuple[list[str], set[str]]:
    """Return the analytics tables referenced and the CTE names. Raises SqlRejected or PolicyDenied."""
    ctes = _cte_names(statement)
    referenced: list[str] = []
    for node in statement.find_all(exp.Func):
        name = _lower_name(node) if isinstance(node, exp.Anonymous) else node.sql_name().lower()
        if name in FORBIDDEN_FUNCTIONS or name.startswith(("pg_", "lo_", "dblink")):
            raise SqlRejected(f"The function {name} is not allowed.", "function")
    for join in statement.find_all(exp.Join):
        if not join.args.get("on") and not join.args.get("using") and not join.args.get("method"):
            raise SqlRejected(
                "Joins must have a condition (cross joins are not allowed).", "cross_join"
            )
    for table in statement.find_all(exp.Table):
        if table.name and table.name.lower() in ctes and not table.args.get("db"):
            continue
        qualified = _analytics_table(table)
        if qualified is None:
            raise SqlRejected(
                "Only analytics tables can be queried.",
                "relation",
            )
        referenced.append(qualified)
    unique = list(dict.fromkeys(referenced))
    policy.check_tables(unique)
    if not unique:
        raise SqlRejected("The query does not read any analytics table.", "no_relation")
    return unique, ctes


def _predicate(rule: RowFilter) -> exp.Expression:
    column = exp.column(rule.column)
    if rule.is_deny_all():
        return exp.false()
    if len(rule.values) == 1:
        return exp.EQ(this=column, expression=exp.Literal.string(rule.values[0]))
    return exp.In(this=column, expressions=[exp.Literal.string(value) for value in rule.values])


def _inner_select(table: str, policy: EffectivePolicy, columns: list[str]) -> exp.Select:
    masked = policy.masked_columns.get(table, frozenset())
    # sqlglot's Alias and Column nodes are not all typed as Expression; Any keeps the builder readable
    projections: list[Any] = []
    for column in columns:
        if column in masked:
            hashed = exp.func("md5", exp.column(column))
            projections.append(exp.alias_(hashed, column))
        else:
            projections.append(exp.column(column))
    where_parts: list[exp.Expression] = [_predicate(rule) for rule in policy.filters_for(table)]
    select = exp.select(*projections).from_(
        exp.Table(
            this=exp.to_identifier(table.split(".", 1)[1]), db=exp.to_identifier(ANALYTICS_SCHEMA)
        )
    )
    if where_parts:
        condition: Any = where_parts[0]
        for part in where_parts[1:]:
            condition = exp.and_(condition, part)
        select = select.where(condition)
    return select


def rewrite(
    statement: exp.Expression,
    policy: EffectivePolicy,
    columns_for: Callable[[str], list[str]],
    max_rows: int,
) -> RewriteResult:
    filtered: list[str] = []
    masked_seen: list[str] = []
    tables: list[str] = []
    for table in list(statement.find_all(exp.Table)):
        qualified = _analytics_table(table)
        if qualified is None:
            continue
        tables.append(qualified)
        needs_filter = bool(policy.filters_for(qualified))
        needs_mask = bool(policy.masked_columns.get(qualified))
        if not needs_filter and not needs_mask:
            continue
        columns = columns_for(qualified)
        if not columns:
            raise SqlRejected(f"No columns are known for {qualified}.", "schema")
        inner = _inner_select(qualified, policy, columns)
        alias = table.alias or table.name
        replacement = exp.Subquery(this=inner, alias=exp.TableAlias(this=exp.to_identifier(alias)))
        table.replace(replacement)
        if needs_filter:
            filtered.append(qualified)
        for column in sorted(policy.masked_columns.get(qualified, frozenset())):
            masked_seen.append(f"{qualified}.{column}")

    if isinstance(statement, exp.Select):
        limit = statement.args.get("limit")
        current = _limit_value(limit)
        if current is None or current > max_rows:
            statement.set("limit", exp.Limit(expression=exp.Literal.number(max_rows)))

    rewritten = statement.sql(dialect=DIALECT)
    parse_single_statement(rewritten)
    notes: list[str] = []
    if filtered:
        notes.append(f"Row filters applied to: {', '.join(sorted(set(filtered)))}.")
    if masked_seen:
        notes.append(f"Masked columns: {', '.join(sorted(set(masked_seen)))}.")
    return RewriteResult(
        sql=rewritten,
        tables=tuple(dict.fromkeys(tables)),
        filtered_tables=tuple(dict.fromkeys(filtered)),
        masked=tuple(dict.fromkeys(masked_seen)),
        notes=notes,
    )


def _limit_value(limit: exp.Expression | None) -> int | None:
    if limit is None:
        return None
    expression = limit.args.get("expression")
    if isinstance(expression, exp.Literal) and expression.is_int:
        return int(expression.name)
    return None


def validate_and_rewrite(
    sql: str,
    policy: EffectivePolicy,
    columns_for: Callable[[str], list[str]],
    max_rows: int,
) -> RewriteResult:
    """Full guard: parse, validate against the policy, then rewrite with row filters and masks."""
    statement = parse_single_statement(sql)
    validate(statement, policy)
    return rewrite(statement, policy, columns_for, max_rows)


__all__ = ["PolicyDenied", "RewriteResult", "SqlRejected", "validate_and_rewrite"]
