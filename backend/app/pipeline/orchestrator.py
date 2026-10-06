"""Query pipeline: question to answer, in ordered, timed steps.

Request flow (section 4.1 of the project plan, cost ladder):
  1 exact cache, 2 semantic cache, 3 rule resolver, 4 LLM plan, 5 LLM SQL fallback, 6 repair.
Every route then goes through the same guard: validation, policy rewrite, cost gate, execution.
Each request writes exactly one audit row, whatever the outcome.

Steps are yielded as events so that the API can stream progress.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import time
import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any, Literal

import structlog
from sqlalchemy import Engine, text

from app.audit.writer import AuditEvent, append_event
from app.auth.service import CurrentUser, RequestContext
from app.core.config import Settings
from app.llm import planner
from app.llm.gateway import GatewayUnavailable, LLMGateway
from app.llm.planner import ModelCall, StructuredOutputError
from app.llm.prompts import all_prompts
from app.llm.providers import LLMResponse, ProviderError
from app.llm.schemas import PlanOutput
from app.pipeline import charts, executor, explain, sql_guard
from app.pipeline.executor import ColumnCatalog, CostRejected
from app.pipeline.shape import humanize
from app.policy.engine import EffectivePolicy, PolicyDenied
from app.policy.loader import load_effective_policy
from app.policy.rls import rls_settings
from app.semantic import catalog
from app.semantic.compiler import CompilerError, MetricFlowCompiler
from app.semantic.embeddings import Embedder
from app.semantic.plan import Filter, MetricPlan, TimeWindow
from app.semantic.rule_resolver import resolve
from app.semantic.vocabulary import Vocabulary

log = structlog.get_logger(__name__)

Route = Literal["cache", "semantic_cache", "rule", "llm_plan", "llm_sql"]
Decision = Literal["allowed", "denied", "clarify", "error"]
CATALOG_METRICS = 6
CATALOG_DIMENSIONS = 8
CATALOG_EXAMPLES = 3
SCHEMA_TABLES = 3
PRICE_NOTE = "Currency is Brazilian Real (BRL)."


@dataclass
class ModelUsage:
    provider: str
    model: str
    tokens_in: int = 0
    tokens_out: int = 0
    latency_ms: int = 0
    calls: int = 0
    prompts: list[str] = field(default_factory=list)

    def add(self, call: ModelCall) -> None:
        response: LLMResponse = call.response
        self.provider = response.provider
        self.model = response.model
        self.tokens_in += response.tokens_in
        self.tokens_out += response.tokens_out
        self.latency_ms += response.latency_ms
        self.calls += 1
        if call.prompt.label not in self.prompts:
            self.prompts.append(call.prompt.label)


@dataclass(frozen=True)
class PipelineEvent:
    kind: Literal["step", "result", "error"]
    data: dict[str, Any]


class PipelineError(Exception):
    """A user facing failure. The message is written in plain language and is safe to show."""

    def __init__(
        self, message: str, decision: Decision = "error", reason: str | None = None
    ) -> None:
        super().__init__(message)
        self.message = message
        self.decision: Decision = decision
        self.reason = reason or message


@dataclass
class Services:
    settings: Settings
    app_engine: Engine
    executor_engine: Engine
    compiler: MetricFlowCompiler
    vocabulary: Vocabulary
    columns: ColumnCatalog
    embedder: Embedder
    gateway: LLMGateway | None


def normalize_question(question: str) -> str:
    return " ".join(question.lower().split())


def cache_key(normalized: str, policy_hash: str) -> str:
    return hashlib.sha256(f"{normalized}|{policy_hash}".encode()).hexdigest()


# Metrics that live in the orders semantic model. They must group by order level dimensions.
ORDER_LEVEL_METRICS = frozenset(
    {
        "payment_value",
        "avg_installments",
        "orders_placed",
        "canceled_orders",
        "cancellation_rate",
        "repeat_orders",
        "repeat_customer_rate",
        "delivered_orders",
        "late_orders",
        "late_delivery_rate",
        "on_time_delivery_rate",
        "avg_delivery_days",
        "avg_review_score",
    }
)
ORDER_DIMENSIONS = frozenset(
    {
        "customer_state",
        "customer_city",
        "order_status",
        "payment_type",
        "review_score",
        "delivery_status",
    }
)


def align_dimensions(plan: MetricPlan) -> MetricPlan:
    """Use the dimension prefix of the semantic model that owns the metrics (order or order_item)."""
    if not plan.metrics or not all(name in ORDER_LEVEL_METRICS for name in plan.metrics):
        return plan
    group_by = []
    for name in plan.group_by:
        converted = name
        if (
            name.startswith("order_item__")
            and name.removeprefix("order_item__") in ORDER_DIMENSIONS
        ):
            converted = "order__" + name.removeprefix("order_item__")
        group_by.append(converted)
    filters = [
        item.model_copy(
            update={"dimension": "order__" + item.dimension.removeprefix("order_item__")}
        )
        if item.dimension.startswith("order_item__")
        and item.dimension.removeprefix("order_item__") in ORDER_DIMENSIONS
        else item
        for item in plan.filters
    ]
    return plan.model_copy(update={"group_by": group_by, "filters": filters})


def _plan_to_json(plan: MetricPlan) -> dict[str, Any]:
    return plan.model_dump(mode="json")


def _plan_from_json(value: dict[str, Any]) -> MetricPlan:
    return MetricPlan.model_validate(value)


def _time_text(window: TimeWindow | None) -> str | None:
    if window is None:
        return None
    last_day = window.end - dt.timedelta(days=1)
    return f"{window.start.isoformat()} to {last_day.isoformat()}"


def _filter_text(item: Filter) -> str:
    parts = item.value if isinstance(item.value, list) else [item.value]
    value = ", ".join(str(part) for part in parts)
    return f"{humanize(item.dimension)} {item.operator} {value}"


class QueryPipeline:
    def __init__(self, services: Services) -> None:
        self._s = services
        self._data_as_of: dt.date | None = None

    # ---- public API -------------------------------------------------------------------------

    def run(
        self,
        question: str,
        user: CurrentUser,
        context: RequestContext,
        session_id: uuid.UUID | None = None,
    ) -> Iterator[PipelineEvent]:
        run = _Run(self, question, user, context, session_id)
        failure: PipelineError | None = None
        try:
            yield from run.execute()
        except PipelineError as error:
            failure = error
        except Exception as error:
            log.error("pipeline_unexpected_error", error_type=type(error).__name__)
            failure = PipelineError(
                "Something went wrong while answering. Try again.", "error", type(error).__name__
            )
        if failure is not None:
            run.fail(failure)
        run.write_audit()
        if failure is None or failure.decision == "clarify":
            if run.payload is not None:
                yield PipelineEvent("result", run.payload)
        else:
            yield PipelineEvent(
                "error",
                {
                    "message": failure.message,
                    "decision": failure.decision,
                    "audit_id": run.audit_id,
                },
            )

    # ---- shared helpers -----------------------------------------------------------------------

    @property
    def services(self) -> Services:
        return self._s

    def data_as_of(self) -> dt.date:
        if self._data_as_of is None:
            with self._s.executor_engine.connect() as connection:
                value = connection.execute(
                    text("SELECT data_as_of_date FROM analytics.int_data_as_of")
                ).scalar()
            self._data_as_of = value if isinstance(value, dt.date) else dt.date.today()
        return self._data_as_of

    def llm_mode(self) -> str:
        with self._s.app_engine.connect() as connection:
            value = connection.execute(
                text("SELECT value FROM app.llm_settings WHERE key = 'llm_mode'")
            ).scalar()
        return str(value or "auto")


class _Run:
    """State for one request. Created per call, never shared between requests."""

    def __init__(
        self,
        pipeline: QueryPipeline,
        question: str,
        user: CurrentUser,
        context: RequestContext,
        session_id: uuid.UUID | None,
    ) -> None:
        self.p = pipeline
        self.s = pipeline._s
        self.question = question.strip()
        self.normalized = normalize_question(question)
        self.user = user
        self.context = context
        self.session_id = session_id
        self.started = time.perf_counter()
        self.policy: EffectivePolicy | None = None
        self.route: Route | None = None
        self.decision: Decision = "error"
        self.denial_reason: str | None = None
        self.plan: MetricPlan | None = None
        self.plan_json: dict[str, Any] | None = None
        self.generated_sql: str | None = None
        self.final_sql: str | None = None
        self.notes: list[str] = []
        self.validation: dict[str, Any] = {}
        self.usage: ModelUsage | None = None
        self.row_count: int | None = None
        self.exec_ms: int | None = None
        self.audit_id: int | None = None
        self.payload: dict[str, Any] | None = None
        self.embedding: list[float] | None = None
        self.clarification: str | None = None
        self.answer: str | None = None
        self._steps: list[str] = []

    # ---- steps ----------------------------------------------------------------------------------

    def step(self, state: str) -> PipelineEvent:
        self._steps.append(state)
        elapsed = int((time.perf_counter() - self.started) * 1000)
        return PipelineEvent("step", {"state": state, "elapsed_ms": elapsed})

    # ---- main flow -------------------------------------------------------------------------------

    def execute(self) -> Iterator[PipelineEvent]:
        if not self.question:
            raise PipelineError("Enter a question.", decision="denied", reason="empty question")
        yield self.step("resolving")
        try:
            self.policy = load_effective_policy(self.s.app_engine, self.user.id)
        except Exception as error:
            raise PipelineError(
                "Your access could not be confirmed. Sign in again.", "denied", "policy"
            ) from error
        self.p.data_as_of()

        cached = self._exact_cache()
        if cached is not None:
            self.route, self.plan, self.generated_sql = "cache", cached[0], cached[1]
        else:
            semantic = self._semantic_cache()
            if semantic is not None:
                self.route, self.plan, self.generated_sql = (
                    "semantic_cache",
                    semantic[0],
                    semantic[1],
                )

        if self.route is None:
            resolution = resolve(self.question, self.s.vocabulary, self.p.data_as_of())
            if resolution.resolved and resolution.plan is not None:
                self.route, self.plan = "rule", resolution.plan
                self.notes.append(f"rule resolver matched: {', '.join(resolution.matched_terms)}")

        if self.route is None:
            yield self.step("planning")
            self._llm_route()

        if (
            self.route in ("cache", "semantic_cache", "rule", "llm_plan")
            and self.generated_sql is None
        ):
            yield self.step("generating")
            self.generated_sql = self._compile()
        self.plan_json = _plan_to_json(self.plan) if self.plan is not None else None

        yield self.step("validating")
        rewrite = self._guard(allow_repair=self.route == "llm_sql")
        self.final_sql = rewrite.sql
        self.validation = {
            "tables": list(rewrite.tables),
            "filtered": list(rewrite.filtered_tables),
            "masked": list(rewrite.masked),
            "rules_passed": True,
        }
        self.notes.extend(rewrite.notes)
        yield self.step("applying_policy")

        yield self.step("executing")
        max_rows = min(self.policy.max_rows, self.s.settings.query_max_rows)
        if self.plan is not None and self.plan.limit is not None:
            max_rows = min(max_rows, self.plan.limit)
        try:
            filters = rls_settings(self.policy)
            executor.enforce_cost_ceiling(
                self.s.executor_engine,
                self.final_sql,
                self.s.settings.explain_cost_ceiling,
                filters,
            )
            result = executor.execute(self.s.executor_engine, self.final_sql, max_rows, filters)
        except CostRejected as error:
            raise PipelineError(
                "This question would scan too much data. Narrow the period or add a filter.",
                "denied",
                f"cost {error.estimated:.0f} above limit",
            ) from error
        except Exception as error:
            log.warning("query_failed", error_type=type(error).__name__)
            raise PipelineError(
                "The query could not run. Try a simpler question.", "error", "execution"
            ) from error
        self.row_count, self.exec_ms = len(result.rows), result.exec_ms

        yield self.step("charting")
        chart = charts.select_chart(result.columns, result.rows)
        explanation = self._explanation(result.columns, result.rows, result.truncated)
        self.answer = explain.answer_text(explanation)
        self._cache_success()
        self.decision = "allowed"
        self.payload = self._payload(result, chart, explanation)
        yield self.step("done")

    # ---- routes -----------------------------------------------------------------------------------

    def _llm_route(self) -> None:
        if self.s.gateway is None:
            raise PipelineError(
                "This question needs the assistant, which is not configured on this server.",
                "error",
                "no LLM provider configured",
            )
        assert self.policy is not None
        self.usage = ModelUsage(provider="", model="")
        embedding = self._embed()
        context_text = self._catalog_context(embedding)
        try:
            output, calls = planner.plan_question(
                self.s.gateway, self.question, context_text, self.p.data_as_of()
            )
        except (GatewayUnavailable, ProviderError) as error:
            raise PipelineError(
                "The assistant is temporarily unavailable. Try again in a minute.",
                "error",
                str(error),
            ) from error
        except StructuredOutputError as error:
            raise PipelineError(
                "I could not turn that into a query. Try rephrasing with a metric and a period.",
                "clarify",
                f"invalid plan: {error}",
            ) from error
        for call in calls:
            self.usage.add(call)

        if output.intent == "clarify":
            self.clarification = output.clarification
            raise PipelineError(
                output.clarification or "Which metric or period do you mean?", "clarify"
            )
        if output.intent == "refuse":
            raise PipelineError(
                output.refusal_reason or "This question is outside the data available to you.",
                "denied",
                "refused by plan",
            )
        if output.intent == "sql_fallback":
            if not self.policy.allow_sql_fallback:
                raise PipelineError(
                    "Your role does not allow free form SQL questions. Try a metric question.",
                    "denied",
                    "sql fallback not allowed",
                )
            self.route = "llm_sql"
            schema_text = self._schema_text()
            try:
                sql, call = planner.generate_sql(self.s.gateway, self.question, schema_text)
            except (GatewayUnavailable, ProviderError) as error:
                raise PipelineError(
                    "The assistant is temporarily unavailable. Try again in a minute.",
                    "error",
                    str(error),
                ) from error
            except StructuredOutputError as error:
                raise PipelineError(
                    "I could not write a query for that question.", "error", str(error)
                ) from error
            self.usage.add(call)
            self.generated_sql = sql
            return

        self.plan = self._plan_from_output(output)
        self.route = "llm_plan"

    def _plan_from_output(self, output: PlanOutput) -> MetricPlan:
        known_metrics = self.s.vocabulary.metric_names()
        unknown = [name for name in output.metrics if name not in known_metrics]
        if unknown:
            raise PipelineError(
                f"I do not know the metric {unknown[0]}. Which measure did you mean?",
                "clarify",
                "unknown metric in plan",
            )
        try:
            return MetricPlan(
                metrics=output.metrics,
                group_by=output.group_by,
                filters=output.filters,
                time_window=output.time_window,
                order_by=output.order_by,
                limit=output.limit,
            )
        except ValueError as error:
            raise PipelineError(
                "I could not build a valid query from that question.",
                "clarify",
                f"invalid plan: {error}",
            ) from error

    # ---- cache -----------------------------------------------------------------------------------

    def _exact_cache(self) -> tuple[MetricPlan, str] | None:
        assert self.policy is not None
        key = cache_key(self.normalized, self.policy.policy_hash)
        with self.s.app_engine.begin() as connection:
            row = (
                connection.execute(
                    text(
                        "SELECT plan_json, generated_sql FROM app.query_cache WHERE cache_key = :key"
                    ),
                    {"key": key},
                )
                .mappings()
                .first()
            )
            if row is None:
                return None
            connection.execute(
                text(
                    "UPDATE app.query_cache SET hit_count = hit_count + 1, last_hit_at = now() WHERE cache_key = :key"
                ),
                {"key": key},
            )
        if row["plan_json"] is None:
            return None
        return _plan_from_json(dict(row["plan_json"])), str(row["generated_sql"])

    def _semantic_cache(self) -> tuple[MetricPlan, str] | None:
        assert self.policy is not None
        if self.s.settings.semantic_cache_threshold >= 1.0:
            return None
        vector = self._embed()
        if vector is None:
            return None
        literal = "[" + ",".join(f"{value:.8f}" for value in vector) + "]"
        with self.s.app_engine.connect() as connection:
            row = (
                connection.execute(
                    text(
                        """
                    SELECT plan_json, generated_sql, 1 - (embedding <=> CAST(:v AS vector)) AS score
                    FROM app.semantic_cache
                    WHERE policy_hash = :policy
                    ORDER BY embedding <=> CAST(:v AS vector)
                    LIMIT 1
                    """
                    ),
                    {"v": literal, "policy": self.policy.policy_hash},
                )
                .mappings()
                .first()
            )
        if row is None or float(row["score"]) < self.s.settings.semantic_cache_threshold:
            return None
        if row["plan_json"] is None or row["generated_sql"] is None:
            return None
        return _plan_from_json(dict(row["plan_json"])), str(row["generated_sql"])

    def _cache_success(self) -> None:
        assert self.policy is not None
        if self.route not in ("rule", "llm_plan") or self.generated_sql is None:
            return
        key = cache_key(self.normalized, self.policy.policy_hash)
        with self.s.app_engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO app.query_cache (cache_key, policy_hash, plan_json, generated_sql)
                    VALUES (:key, :policy, CAST(:plan AS JSONB), :sql)
                    ON CONFLICT (cache_key) DO UPDATE SET plan_json = EXCLUDED.plan_json,
                        generated_sql = EXCLUDED.generated_sql
                    """
                ),
                {
                    "key": key,
                    "policy": self.policy.policy_hash,
                    "plan": _json(self.plan_json),
                    "sql": self.generated_sql,
                },
            )
            if self.embedding is not None and self.plan_json is not None:
                literal = "[" + ",".join(f"{value:.8f}" for value in self.embedding) + "]"
                connection.execute(
                    text(
                        """
                        INSERT INTO app.semantic_cache (policy_hash, question, embedding, plan_json, generated_sql)
                        VALUES (:policy, :question, CAST(:v AS vector), CAST(:plan AS JSONB), :sql)
                        """
                    ),
                    {
                        "policy": self.policy.policy_hash,
                        "question": self.normalized,
                        "v": literal,
                        "plan": _json(self.plan_json),
                        "sql": self.generated_sql,
                    },
                )

    # ---- compile, validate ---------------------------------------------------------------------

    def _compile(self) -> str:
        assert self.plan is not None
        self.plan = align_dimensions(self.plan)
        try:
            return self.s.compiler.explain(self.plan)
        except CompilerError as error:
            raise PipelineError(
                "I could not build a query for that question. Try a metric name and a period.",
                "clarify",
                f"metricflow: {error}",
            ) from error

    def _guard(self, *, allow_repair: bool) -> sql_guard.RewriteResult:
        assert self.policy is not None and self.generated_sql is not None
        max_rows = min(self.policy.max_rows, self.s.settings.query_max_rows)
        try:
            return sql_guard.validate_and_rewrite(
                self.generated_sql, self.policy, self.s.columns.columns_for, max_rows
            )
        except PolicyDenied as denied:
            raise PipelineError(denied.reason, "denied", denied.reason) from denied
        except sql_guard.SqlRejected as rejected:
            if not allow_repair or self.s.gateway is None:
                raise PipelineError(
                    rejected.reason, "denied", f"validation: {rejected.rule}"
                ) from rejected
            return self._repair(rejected.reason, max_rows)

    def _repair(self, error: str, max_rows: int) -> sql_guard.RewriteResult:
        assert self.policy is not None and self.s.gateway is not None and self.usage is not None
        try:
            sql, call = planner.repair_sql(
                self.s.gateway, self.question, self._schema_text(), self.generated_sql or "", error
            )
        except (GatewayUnavailable, ProviderError, StructuredOutputError) as failure:
            raise PipelineError(
                "I could not write a valid query for that question.", "denied", str(failure)
            ) from failure
        self.usage.add(call)
        self.generated_sql = sql
        try:
            return sql_guard.validate_and_rewrite(
                sql, self.policy, self.s.columns.columns_for, max_rows
            )
        except PolicyDenied as denied:
            raise PipelineError(denied.reason, "denied", denied.reason) from denied
        except sql_guard.SqlRejected as rejected:
            raise PipelineError(
                rejected.reason, "denied", f"validation after repair: {rejected.rule}"
            ) from rejected

    # ---- context for the model -------------------------------------------------------------------

    def _embed(self) -> list[float] | None:
        if self.embedding is None:
            try:
                self.embedding = self.s.embedder.embed_query(self.normalized)
            except Exception as error:
                log.warning("embedding_unavailable", error_type=type(error).__name__)
                return None
        return self.embedding

    def _catalog_context(self, embedding: list[float] | None) -> str:
        if embedding is None:
            names = sorted(self.s.vocabulary.metric_names())
            lines = [
                f"metric {name}: {self.s.vocabulary.metrics[name].description}" for name in names
            ]
            return "\n".join(lines)
        with self.s.app_engine.connect() as connection:
            metrics = catalog.search(connection, embedding, CATALOG_METRICS, kinds=("metric",))
            dimensions = catalog.search(
                connection, embedding, CATALOG_DIMENSIONS, kinds=("dimension",)
            )
            examples = catalog.search(connection, embedding, CATALOG_EXAMPLES, kinds=("example",))
        lines = [f"metric {hit.name}: {hit.content} (metric)" for hit in metrics]
        lines += [f"dimension {hit.name}: {hit.content} (dimension)" for hit in dimensions]
        lines += [f"example question: {hit.content}" for hit in examples]
        return "\n".join(lines)

    def _schema_text(self) -> str:
        assert self.policy is not None
        lines: list[str] = []
        for table in sorted(self.policy.allowed_tables)[:SCHEMA_TABLES]:
            columns = self.s.columns.columns_for(table)
            lines.append(f"{table}({', '.join(columns)})")
        return "\n".join(lines) or "(no tables are available to this role)"

    # ---- results ---------------------------------------------------------------------------------

    def _explanation(self, columns: list[str], rows: list[list[Any]], truncated: bool) -> list[str]:
        assert self.policy is not None
        metrics = list(self.plan.metrics) if self.plan is not None else []
        descriptions = {
            name: self.s.vocabulary.metrics[name].description
            for name in metrics
            if name in self.s.vocabulary.metrics
        }
        filters = [_filter_text(item) for item in (self.plan.filters if self.plan else [])]
        lines = explain.build_explanation(
            columns=columns,
            rows=rows,
            metrics=metrics,
            metric_descriptions=descriptions,
            filters=filters,
            time_text=_time_text(self.plan.time_window) if self.plan else None,
            truncated=truncated,
        )
        if metrics and any(
            name in ("revenue", "gmv", "aov", "freight_revenue", "payment_value")
            for name in metrics
        ):
            lines.append(PRICE_NOTE)
        return lines

    def _payload(
        self, result: executor.ExecutionResult, chart: dict[str, Any], explanation: list[str]
    ) -> dict[str, Any]:
        usage = self.usage
        return {
            "answer_text": self.answer,
            "route": self.route,
            "decision": "allowed",
            "plan": self.plan_json,
            "sql": {"generated": self.generated_sql, "final": self.final_sql},
            "columns": result.columns,
            "rows": [[_jsonable(value) for value in row] for row in result.rows],
            "truncated": result.truncated,
            "chart_spec": chart,
            "explanation": explanation,
            "policy_notes": self.notes,
            "usage": {
                "provider": usage.provider if usage else None,
                "model": usage.model if usage else None,
                "tokens_in": usage.tokens_in if usage else 0,
                "tokens_out": usage.tokens_out if usage else 0,
                "latency_ms": usage.latency_ms if usage else 0,
                "model_calls": usage.calls if usage else 0,
                "prompt_versions": usage.prompts if usage else [],
            },
            "clarification": None,
            "audit_id": None,
            "steps": self._steps,
        }

    def fail(self, error: PipelineError) -> None:
        self.decision = error.decision
        self.denial_reason = error.reason
        if error.decision == "clarify":
            self.clarification = error.message

    # ---- audit -----------------------------------------------------------------------------------

    def write_audit(self) -> None:
        total_ms = int((time.perf_counter() - self.started) * 1000)
        usage = self.usage
        prompt_versions = ",".join(all_prompt_labels(usage))
        event = AuditEvent(
            event="query",
            decision=self.decision,
            user_id=self.user.id,
            role=self.user.role,
            session_id=self.session_id,
            question=self.question,
            normalized_question=self.normalized,
            route=self.route or "none",
            provider=usage.provider if usage and usage.provider else None,
            model=usage.model if usage and usage.model else None,
            prompt_version=prompt_versions or None,
            tokens_in=usage.tokens_in if usage else 0,
            tokens_out=usage.tokens_out if usage else 0,
            plan_json=self.plan_json,
            generated_sql=self.generated_sql,
            final_sql=self.final_sql,
            validation_result=self.validation or None,
            policy_hash=self.policy.policy_hash if self.policy else None,
            denial_reason=self.denial_reason,
            row_count=self.row_count,
            exec_ms=self.exec_ms,
            total_ms=total_ms,
            client_ip=self.context.client_ip,
            request_id=self.context.request_id,
        )
        with self.s.app_engine.begin() as connection:
            self.audit_id = append_event(connection, event)
        if self.payload is not None:
            self.payload["audit_id"] = self.audit_id
            self.payload["steps"] = self._steps
        elif self.decision == "clarify":
            self.payload = {
                "answer_text": self.clarification,
                "route": self.route,
                "decision": "clarify",
                "clarification": self.clarification,
                "audit_id": self.audit_id,
                "steps": self._steps,
            }
        self._persist_chat()

    def _persist_chat(self) -> None:
        try:
            with self.s.app_engine.begin() as connection:
                session = self.session_id
                if session is None:
                    session = connection.execute(
                        text(
                            "INSERT INTO app.chat_sessions (user_id, title) VALUES (CAST(:u AS UUID), :t) RETURNING id"
                        ),
                        {"u": str(self.user.id), "t": self.question[:80]},
                    ).scalar_one()
                    self.session_id = session
                connection.execute(
                    text(
                        "INSERT INTO app.chat_messages (session_id, role, content) VALUES (:s, 'user', CAST(:c AS JSONB))"
                    ),
                    {"s": str(session), "c": _json({"question": self.question})},
                )
                connection.execute(
                    text(
                        "INSERT INTO app.chat_messages (session_id, role, content) VALUES (:s, 'assistant', CAST(:c AS JSONB))"
                    ),
                    {
                        "s": str(session),
                        "c": _json(
                            {
                                "decision": self.decision,
                                "answer": self.answer or self.clarification or self.denial_reason,
                                "audit_id": self.audit_id,
                            }
                        ),
                    },
                )
        except Exception as error:
            log.warning("chat_persist_failed", error_type=type(error).__name__)


def all_prompt_labels(usage: ModelUsage | None) -> list[str]:
    if usage is None:
        return []
    known = {prompt.label for prompt in all_prompts()}
    return [label for label in usage.prompts if label in known]


def _json(value: Any) -> str:
    return json.dumps(value, default=str)


def _jsonable(value: Any) -> Any:
    if isinstance(value, (dt.date, dt.datetime)):
        return value.isoformat()
    if hasattr(value, "__float__") and not isinstance(value, (int, bool)):
        return float(value)
    return value
