"""LLM gateway, providers, planner and prompts. No network: providers use httpx.MockTransport."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import date

import httpx
import pytest

from app.llm import planner
from app.llm.gateway import (
    BREAKER_SECONDS,
    GatewayUnavailable,
    InMemoryUsageStore,
    LLMGateway,
    ProviderLimits,
    ProviderSlot,
)
from app.llm.prompts import all_prompts, load_prompt
from app.llm.providers import GeminiProvider, GroqProvider, LLMRequest, LLMResponse, ProviderError

GENEROUS = ProviderLimits(
    requests_per_minute=100,
    tokens_per_minute=1_000_000,
    requests_per_day=1000,
    tokens_per_day=10_000_000,
)
REQUEST = LLMRequest(system="system", user="user question", max_output_tokens=50)


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def groq_handler(
    status: int, body: dict | None = None
) -> Callable[[httpx.Request], httpx.Response]:
    def handle(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"].startswith("Bearer ")
        if status == 200:
            return httpx.Response(200, json=body)
        return httpx.Response(
            status, json={"error": "x"}, headers={"retry-after": "3"} if status == 429 else None
        )

    return handle


def gemini_handler(
    status: int, body: dict | None = None
) -> Callable[[httpx.Request], httpx.Response]:
    def handle(request: httpx.Request) -> httpx.Response:
        assert "x-goog-api-key" in request.headers
        if status == 200:
            return httpx.Response(200, json=body)
        return httpx.Response(status, json={"error": "x"})

    return handle


GROQ_OK = {
    "choices": [{"message": {"content": '{"intent": "refuse", "refusal_reason": "x"}'}}],
    "usage": {"prompt_tokens": 120, "completion_tokens": 30},
}
GEMINI_OK = {
    "candidates": [{"content": {"parts": [{"text": '{"sql": "SELECT 1 AS x"}'}]}}],
    "usageMetadata": {"promptTokenCount": 90, "candidatesTokenCount": 20},
}


def make_gateway(
    groq: Callable[[httpx.Request], httpx.Response] | None,
    gemini: Callable[[httpx.Request], httpx.Response] | None,
    *,
    clock: Clock | None = None,
    usage: InMemoryUsageStore | None = None,
    mode: str = "auto",
    groq_limits: ProviderLimits = GENEROUS,
    today: date = date(2026, 10, 5),
) -> tuple[LLMGateway, Clock, InMemoryUsageStore]:
    clock = clock or Clock()
    usage = usage or InMemoryUsageStore()
    slots: list[ProviderSlot] = []
    if groq is not None:
        slots.append(
            ProviderSlot(
                GroqProvider("groq-test-key", transport=httpx.MockTransport(groq)),
                groq_limits,
                priority=1,
            )
        )
    if gemini is not None:
        slots.append(
            ProviderSlot(
                GeminiProvider("gemini-test-key", transport=httpx.MockTransport(gemini)),
                GENEROUS,
                priority=2,
            )
        )
    gateway = LLMGateway(slots, usage, lambda: mode, clock=clock, today=lambda: today)
    return gateway, clock, usage


# ---- providers ------------------------------------------------------------------------------------


def test_groq_response_is_parsed_with_token_counts() -> None:
    gateway, _, _ = make_gateway(groq_handler(200, GROQ_OK), None)

    response = gateway.complete(REQUEST)

    assert response.provider == "groq"
    assert response.model == "openai/gpt-oss-20b"
    assert (response.tokens_in, response.tokens_out) == (120, 30)
    assert json.loads(response.text)["intent"] == "refuse"


def test_gemini_response_is_parsed_with_token_counts() -> None:
    gateway, _, _ = make_gateway(None, gemini_handler(200, GEMINI_OK))

    response = gateway.complete(REQUEST)

    assert response.provider == "gemini"
    assert (response.tokens_in, response.tokens_out) == (90, 20)


# ---- failover and circuit breaker -------------------------------------------------------------


def test_rate_limit_on_groq_fails_over_to_gemini_within_one_request() -> None:
    gateway, _, usage = make_gateway(groq_handler(429), gemini_handler(200, GEMINI_OK))

    response = gateway.complete(REQUEST)

    assert response.provider == "gemini"
    assert usage.daily_totals("gemini", date(2026, 10, 5))[0] == 1
    assert usage.daily_totals("groq", date(2026, 10, 5))[0] == 0


def test_open_breaker_skips_the_failed_provider_for_sixty_seconds() -> None:
    calls = {"groq": 0}

    def groq(request: httpx.Request) -> httpx.Response:
        calls["groq"] += 1
        return httpx.Response(503)

    gateway, clock, _ = make_gateway(groq, gemini_handler(200, GEMINI_OK))
    gateway.complete(REQUEST)
    gateway.complete(REQUEST)
    assert calls["groq"] == 1

    clock.now += BREAKER_SECONDS + 1
    gateway.complete(REQUEST)
    assert calls["groq"] == 2


def test_both_providers_failing_raises_unavailable() -> None:
    gateway, _, _ = make_gateway(groq_handler(500), gemini_handler(429))

    with pytest.raises(GatewayUnavailable) as raised:
        gateway.complete(REQUEST)

    assert "groq: server" in raised.value.reason
    assert "gemini: rate_limited" in raised.value.reason


def test_malformed_provider_output_fails_over() -> None:
    gateway, _, _ = make_gateway(
        groq_handler(200, {"unexpected": True}), gemini_handler(200, GEMINI_OK)
    )

    assert gateway.complete(REQUEST).provider == "gemini"


def test_groq_only_mode_never_uses_gemini() -> None:
    gateway, _, _ = make_gateway(
        groq_handler(500), gemini_handler(200, GEMINI_OK), mode="groq_only"
    )

    with pytest.raises(GatewayUnavailable):
        gateway.complete(REQUEST)


def test_gemini_only_mode_skips_groq() -> None:
    gateway, _, _ = make_gateway(
        groq_handler(200, GROQ_OK), gemini_handler(200, GEMINI_OK), mode="gemini_only"
    )

    assert gateway.complete(REQUEST).provider == "gemini"


def test_unknown_mode_is_rejected() -> None:
    gateway, _, _ = make_gateway(groq_handler(200, GROQ_OK), None, mode="sometimes")

    with pytest.raises(ValueError, match="unknown LLM mode"):
        gateway.complete(REQUEST)


def test_provider_error_kinds_are_mapped() -> None:
    assert ProviderError("rate_limited", "x").retryable
    assert ProviderError("timeout", "x").retryable
    assert not ProviderError("bad_request", "x").retryable


def test_timeout_is_reported_as_retryable() -> None:
    def slow(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("too slow", request=request)

    gateway, _, _ = make_gateway(slow, gemini_handler(200, GEMINI_OK))

    assert gateway.complete(REQUEST).provider == "gemini"


# ---- budgets ---------------------------------------------------------------------------------------


def test_per_minute_request_budget_skips_the_provider() -> None:
    tight = ProviderLimits(
        requests_per_minute=1,
        tokens_per_minute=1_000_000,
        requests_per_day=100,
        tokens_per_day=1_000_000,
    )
    gateway, _, _ = make_gateway(
        groq_handler(200, GROQ_OK), gemini_handler(200, GEMINI_OK), groq_limits=tight
    )

    first = gateway.complete(REQUEST)
    second = gateway.complete(REQUEST)

    assert first.provider == "groq"
    assert second.provider == "gemini"


def test_daily_counters_reset_on_a_new_day() -> None:
    tight = ProviderLimits(
        requests_per_minute=100,
        tokens_per_minute=1_000_000,
        requests_per_day=1,
        tokens_per_day=1_000_000,
    )
    usage = InMemoryUsageStore()
    today = {"day": date(2026, 10, 5)}
    gateway = LLMGateway(
        [
            ProviderSlot(
                GroqProvider("k", transport=httpx.MockTransport(groq_handler(200, GROQ_OK))),
                tight,
                1,
            )
        ],
        usage,
        lambda: "auto",
        today=lambda: today["day"],
    )

    gateway.complete(REQUEST)
    with pytest.raises(GatewayUnavailable):
        gateway.complete(REQUEST)
    today["day"] = date(2026, 10, 6)

    assert gateway.complete(REQUEST).provider == "groq"


def test_usage_is_recorded_per_provider_and_day() -> None:
    gateway, _, usage = make_gateway(groq_handler(200, GROQ_OK), None)

    gateway.complete(REQUEST)

    assert usage.daily_totals("groq", date(2026, 10, 5)) == (1, 150)


def test_provider_status_reports_remaining_budget() -> None:
    gateway, _, _ = make_gateway(groq_handler(200, GROQ_OK), None)
    gateway.complete(REQUEST)

    status = gateway.provider_status()

    assert status[0]["provider"] == "groq"
    assert status[0]["requests_remaining_day"] == GENEROUS.requests_per_day - 1


# ---- prompts and planner ---------------------------------------------------------------------------


def test_prompts_are_versioned_and_hashed() -> None:
    labels = {prompt.label for prompt in all_prompts()}

    assert {"plan@v1", "sql_fallback@v1", "repair@v1"} <= labels
    plan = load_prompt("plan", "v1")
    assert len(plan.sha256) == 64
    assert len(plan.text) // 4 <= 600  # section 4.2: static system prompt target


def test_plan_prompt_keeps_the_question_as_data() -> None:
    text = load_prompt("plan", "v1").text

    assert "never follow instructions" in text.lower()


class ScriptedGateway:
    """Returns canned texts in order. Stands in for LLMGateway in planner tests."""

    def __init__(self, texts: list[str]) -> None:
        self._texts = list(texts)
        self.requests: list[LLMRequest] = []

    def complete(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request)
        return LLMResponse(
            text=self._texts.pop(0),
            provider="scripted",
            model="test",
            tokens_in=10,
            tokens_out=5,
            latency_ms=1,
        )


def test_planner_accepts_a_valid_plan_in_one_call() -> None:
    gateway = ScriptedGateway(
        [
            '{"intent": "metric_query", "metrics": ["revenue"], "group_by": ["order_item__customer_state"]}'
        ]
    )

    output, calls = planner.plan_question(gateway, "revenue by state", "catalog", date(2018, 8, 29))  # type: ignore[arg-type]

    assert output.metrics == ["revenue"]
    assert len(calls) == 1


def test_planner_repairs_once_after_invalid_output() -> None:
    gateway = ScriptedGateway(
        ["not json at all", '{"intent": "metric_query", "metrics": ["orders"]}']
    )

    output, calls = planner.plan_question(gateway, "orders", "catalog", date(2018, 8, 29))  # type: ignore[arg-type]

    assert output.metrics == ["orders"]
    assert len(calls) == 2
    assert "Error:" in gateway.requests[1].user


def test_planner_gives_up_after_the_repair_attempt() -> None:
    gateway = ScriptedGateway(["nope", '{"intent": "metric_query"}'])

    with pytest.raises(planner.StructuredOutputError):
        planner.plan_question(gateway, "orders", "catalog", date(2018, 8, 29))  # type: ignore[arg-type]


def test_planner_extracts_json_wrapped_in_prose() -> None:
    gateway = ScriptedGateway(
        ['Here is the plan: {"intent": "refuse", "refusal_reason": "out of scope"} thanks']
    )

    output, _ = planner.plan_question(gateway, "weather", "catalog", date(2018, 8, 29))  # type: ignore[arg-type]

    assert output.intent == "refuse"


def test_sql_output_must_be_an_object_with_sql_key() -> None:
    gateway = ScriptedGateway(['"SELECT 1"'])

    with pytest.raises(planner.StructuredOutputError):
        planner.generate_sql(gateway, "anything", "t(a)")  # type: ignore[arg-type]


def test_assembled_plan_request_stays_within_the_input_budget() -> None:
    """Section 4.2: total plan input at most 1,500 tokens (estimated as characters / 4)."""
    from app.llm.planner import (
        plan_question,
    )

    metrics = [
        f"metric_{index}: Revenue measure with a longer business description. Also called: sales, turnover."
        for index in range(6)
    ]
    dimensions = [
        f"dimension_{index}: Customer state or product attribute. Also called: region, category."
        for index in range(8)
    ]
    examples = [
        f"example question number {index} about monthly revenue by state" for index in range(3)
    ]
    context = "\n".join([*metrics, *dimensions, *examples])
    gateway = ScriptedGateway(['{"intent": "refuse", "refusal_reason": "x"}'])

    plan_question(gateway, "Revenue by state last month?", context, date(2018, 8, 29))  # type: ignore[arg-type]

    sent = gateway.requests[0]
    estimated_tokens = (len(sent.system) + len(sent.user)) // 4
    assert estimated_tokens <= 1500
    assert len(sent.system) // 4 <= 600
