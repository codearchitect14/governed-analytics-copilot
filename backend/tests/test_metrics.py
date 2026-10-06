"""Metrics registry and middleware: counters, histogram buckets and Prometheus text output."""

from __future__ import annotations

import pytest
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from app.core.metrics import BUCKETS, MetricsMiddleware, Registry


def test_histogram_buckets_are_cumulative() -> None:
    registry = Registry()
    registry.record("GET", "/x", 200, 0.02)
    registry.record("GET", "/x", 200, 0.7)

    text = registry.render()

    assert 'http_request_duration_seconds_bucket{method="GET",route="/x",le="0.05"} 1' in text
    assert 'http_request_duration_seconds_bucket{method="GET",route="/x",le="1.0"} 2' in text
    assert 'http_request_duration_seconds_bucket{method="GET",route="/x",le="+Inf"} 2' in text
    assert 'http_request_duration_seconds_count{method="GET",route="/x"} 2' in text


def test_request_counter_is_labelled_by_status() -> None:
    registry = Registry()
    registry.record("POST", "/a", 401, 0.01)
    registry.record("POST", "/a", 401, 0.01)
    registry.record("POST", "/a", 200, 0.01)

    text = registry.render()

    assert 'http_requests_total{method="POST",route="/a",status="401"} 2' in text
    assert 'http_requests_total{method="POST",route="/a",status="200"} 1' in text


def test_middleware_records_route_template_and_status() -> None:
    async def item(request):  # type: ignore[no-untyped-def]
        return PlainTextResponse("ok", status_code=201)

    registry = Registry()
    app = Starlette(routes=[Route("/items/{item_id}", item)])
    app.add_middleware(MetricsMiddleware, registry=registry, routes=app.routes)  # type: ignore[arg-type]

    with TestClient(app) as client:
        assert client.get("/items/42").status_code == 201
        assert client.get("/missing").status_code == 404

    text = registry.render()
    assert 'route="/items/{item_id}",status="201"' in text
    assert 'route="unmatched",status="404"' in text


def test_bucket_bounds_are_sorted() -> None:
    assert list(BUCKETS) == sorted(BUCKETS)


@pytest.mark.parametrize("seconds", [0.0, 10.0])
def test_extreme_latencies_are_counted_in_inf(seconds: float) -> None:
    registry = Registry()
    registry.record("GET", "/y", 200, seconds)

    assert 'le="+Inf"} 1' in registry.render()
