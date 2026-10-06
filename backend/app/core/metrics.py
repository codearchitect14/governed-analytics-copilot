"""In-process HTTP metrics exposed in Prometheus text format at /metrics."""

from __future__ import annotations

import threading
import time
from collections import defaultdict
from collections.abc import Sequence

from starlette.routing import BaseRoute, Match
from starlette.types import ASGIApp, Message, Receive, Scope, Send

BUCKETS: tuple[float, ...] = (0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0)
UNMATCHED = "unmatched"


def _labels(**pairs: str) -> str:
    return "{" + ",".join(f'{key}="{value}"' for key, value in pairs.items()) + "}"


class Registry:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._requests: dict[tuple[str, str, int], int] = defaultdict(int)
        self._buckets: dict[tuple[str, str], list[int]] = {}
        self._sums: dict[tuple[str, str], float] = defaultdict(float)

    def record(self, method: str, route: str, status: int, seconds: float) -> None:
        key = (method, route)
        with self._lock:
            self._requests[(method, route, status)] += 1
            counts = self._buckets.setdefault(key, [0] * (len(BUCKETS) + 1))
            for index, bound in enumerate(BUCKETS):
                if seconds <= bound:
                    counts[index] += 1
            counts[-1] += 1
            self._sums[key] += seconds

    def render(self) -> str:
        lines = [
            "# HELP http_requests_total Completed HTTP requests by method, route and status.",
            "# TYPE http_requests_total counter",
        ]
        with self._lock:
            for (method, route, status), count in sorted(self._requests.items()):
                labels = _labels(method=method, route=route, status=str(status))
                lines.append(f"http_requests_total{labels} {count}")
            lines.extend(
                [
                    "# HELP http_request_duration_seconds Request latency by method and route.",
                    "# TYPE http_request_duration_seconds histogram",
                ]
            )
            for key in sorted(self._buckets):
                method, route = key
                counts = self._buckets[key]
                for index, bound in enumerate(BUCKETS):
                    labels = _labels(method=method, route=route, le=str(bound))
                    lines.append(f"http_request_duration_seconds_bucket{labels} {counts[index]}")
                labels = _labels(method=method, route=route, le="+Inf")
                lines.append(f"http_request_duration_seconds_bucket{labels} {counts[-1]}")
                labels = _labels(method=method, route=route)
                lines.append(f"http_request_duration_seconds_sum{labels} {self._sums[key]:.6f}")
                lines.append(f"http_request_duration_seconds_count{labels} {counts[-1]}")
        return "\n".join(lines) + "\n"


REGISTRY = Registry()


class MetricsMiddleware:
    def __init__(
        self,
        app: ASGIApp,
        registry: Registry = REGISTRY,
        routes: Sequence[BaseRoute] = (),
    ) -> None:
        self.app = app
        self._registry = registry
        self._routes = routes

    def _template(self, scope: Scope) -> str:
        for route in self._routes:
            match, _ = route.matches(scope)
            if match == Match.FULL:
                return str(getattr(route, "path", UNMATCHED))
        return UNMATCHED

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        status_code = 500
        started = time.perf_counter()

        async def capture_status(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = int(message["status"])
            await send(message)

        try:
            await self.app(scope, receive, capture_status)
        finally:
            self._registry.record(
                str(scope.get("method", "GET")),
                self._template(scope),
                status_code,
                time.perf_counter() - started,
            )
