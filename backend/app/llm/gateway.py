"""LLM gateway: provider order, local rate budgets, daily counters, circuit breaker, failover.

Policy:
- Providers are tried in priority order (Groq, then Gemini) subject to the admin mode.
- A provider whose per minute or per day budget is spent is skipped, not failed.
- A retryable failure (rate limit, server error, timeout) or an auth failure opens that
  provider's circuit breaker for 60 seconds, and the request fails over to the next provider.
- At most two provider attempts are made per request.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Protocol

from sqlalchemy import Engine, text

from app.llm.providers import LLMProvider, LLMRequest, LLMResponse, ProviderError

MODES = ("auto", "groq_only", "gemini_only")
MAX_ATTEMPTS = 2
BREAKER_SECONDS = 60.0
MINUTE_SECONDS = 60.0
CHARS_PER_TOKEN = 4


class GatewayUnavailable(Exception):
    """No provider could serve the request. The reason is safe to log, not to show users."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class ProviderLimits:
    requests_per_minute: int
    tokens_per_minute: int
    requests_per_day: int
    tokens_per_day: int


@dataclass(frozen=True)
class ProviderSlot:
    provider: LLMProvider
    limits: ProviderLimits
    priority: int


class UsageStore(Protocol):
    def daily_totals(self, provider: str, day: date) -> tuple[int, int]: ...

    def record(
        self, provider: str, model: str, day: date, tokens_in: int, tokens_out: int
    ) -> None: ...


class InMemoryUsageStore:
    """Usage store for tests and for runs without a database."""

    def __init__(self) -> None:
        self._totals: dict[tuple[str, date], list[int]] = {}
        self._lock = threading.Lock()

    def daily_totals(self, provider: str, day: date) -> tuple[int, int]:
        with self._lock:
            requests, tokens = self._totals.get((provider, day), [0, 0])
            return requests, tokens

    def record(self, provider: str, model: str, day: date, tokens_in: int, tokens_out: int) -> None:
        with self._lock:
            entry = self._totals.setdefault((provider, day), [0, 0])
            entry[0] += 1
            entry[1] += tokens_in + tokens_out


class DatabaseUsageStore:
    """Daily counters in app.llm_usage. One row per day, provider and model."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def daily_totals(self, provider: str, day: date) -> tuple[int, int]:
        with self._engine.connect() as connection:
            row = connection.execute(
                text(
                    """
                    SELECT COALESCE(SUM(requests), 0) AS requests,
                           COALESCE(SUM(tokens_in + tokens_out), 0) AS tokens
                    FROM app.llm_usage WHERE usage_date = :day AND provider = :provider
                    """
                ),
                {"day": day, "provider": provider},
            ).one()
        return int(row.requests), int(row.tokens)

    def record(self, provider: str, model: str, day: date, tokens_in: int, tokens_out: int) -> None:
        with self._engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO app.llm_usage (usage_date, provider, model, requests, tokens_in, tokens_out)
                    VALUES (:day, :provider, :model, 1, :tokens_in, :tokens_out)
                    ON CONFLICT (usage_date, provider, model) DO UPDATE SET
                        requests = app.llm_usage.requests + 1,
                        tokens_in = app.llm_usage.tokens_in + EXCLUDED.tokens_in,
                        tokens_out = app.llm_usage.tokens_out + EXCLUDED.tokens_out
                    """
                ),
                {
                    "day": day,
                    "provider": provider,
                    "model": model,
                    "tokens_in": tokens_in,
                    "tokens_out": tokens_out,
                },
            )


class SlidingMinute:
    """Requests and tokens in the last 60 seconds for one provider."""

    def __init__(self, clock: Callable[[], float]) -> None:
        self._clock = clock
        self._events: deque[tuple[float, int]] = deque()

    def _trim(self) -> None:
        cutoff = self._clock() - MINUTE_SECONDS
        while self._events and self._events[0][0] < cutoff:
            self._events.popleft()

    def usage(self) -> tuple[int, int]:
        self._trim()
        return len(self._events), sum(tokens for _, tokens in self._events)

    def add(self, tokens: int) -> None:
        self._trim()
        self._events.append((self._clock(), tokens))


@dataclass
class CircuitBreaker:
    clock: Callable[[], float]
    opened_until: dict[str, float] = field(default_factory=dict)

    def open(self, provider: str) -> None:
        self.opened_until[provider] = self.clock() + BREAKER_SECONDS

    def is_open(self, provider: str) -> bool:
        return self.opened_until.get(provider, 0.0) > self.clock()


class LLMGateway:
    def __init__(
        self,
        slots: Sequence[ProviderSlot],
        usage: UsageStore,
        mode_source: Callable[[], str] = lambda: "auto",
        *,
        clock: Callable[[], float] = time.monotonic,
        today: Callable[[], date] = date.today,
    ) -> None:
        self._slots = sorted(slots, key=lambda slot: slot.priority)
        self._usage = usage
        self._mode_source = mode_source
        self._clock = clock
        self._today = today
        self._minutes = {slot.provider.name: SlidingMinute(clock) for slot in self._slots}
        self._breaker = CircuitBreaker(clock)

    def _candidates(self) -> list[ProviderSlot]:
        mode = self._mode_source()
        if mode not in MODES:
            raise ValueError(f"unknown LLM mode {mode!r}")
        if mode == "groq_only":
            return [slot for slot in self._slots if slot.provider.name == "groq"]
        if mode == "gemini_only":
            return [slot for slot in self._slots if slot.provider.name == "gemini"]
        return list(self._slots)

    def _budget_allows(self, slot: ProviderSlot, estimated_tokens: int) -> bool:
        name = slot.provider.name
        requests_minute, tokens_minute = self._minutes[name].usage()
        if requests_minute + 1 > slot.limits.requests_per_minute:
            return False
        if tokens_minute + estimated_tokens > slot.limits.tokens_per_minute:
            return False
        requests_day, tokens_day = self._usage.daily_totals(name, self._today())
        if requests_day + 1 > slot.limits.requests_per_day:
            return False
        return tokens_day + estimated_tokens <= slot.limits.tokens_per_day

    def provider_status(self) -> list[dict[str, object]]:
        """Remaining budget per provider, for the operations page."""
        status: list[dict[str, object]] = []
        for slot in self._slots:
            name = slot.provider.name
            requests_minute, tokens_minute = self._minutes[name].usage()
            requests_day, tokens_day = self._usage.daily_totals(name, self._today())
            status.append(
                {
                    "provider": name,
                    "model": slot.provider.model,
                    "circuit_open": self._breaker.is_open(name),
                    "requests_remaining_minute": slot.limits.requests_per_minute - requests_minute,
                    "tokens_remaining_minute": slot.limits.tokens_per_minute - tokens_minute,
                    "requests_remaining_day": slot.limits.requests_per_day - requests_day,
                    "tokens_remaining_day": slot.limits.tokens_per_day - tokens_day,
                }
            )
        return status

    def complete(self, request: LLMRequest) -> LLMResponse:
        estimated = (
            len(request.system) + len(request.user)
        ) // CHARS_PER_TOKEN + request.max_output_tokens
        attempts = 0
        reasons: list[str] = []
        for slot in self._candidates():
            if attempts >= MAX_ATTEMPTS:
                break
            name = slot.provider.name
            if self._breaker.is_open(name):
                reasons.append(f"{name}: circuit open")
                continue
            if not self._budget_allows(slot, estimated):
                reasons.append(f"{name}: budget exhausted")
                continue
            attempts += 1
            try:
                response = slot.provider.complete(request)
            except ProviderError as error:
                reasons.append(f"{name}: {error.kind}")
                if error.retryable or error.kind == "auth":
                    self._breaker.open(name)
                continue
            self._minutes[name].add(response.tokens_in + response.tokens_out)
            self._usage.record(
                name, response.model, self._today(), response.tokens_in, response.tokens_out
            )
            return response
        raise GatewayUnavailable("; ".join(reasons) or "no provider is configured for this mode")
