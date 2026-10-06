"""Phase 7: dashboards, operations analytics and demo history.

The dashboard tests need the dev analytics marts (skipped otherwise). The seeder and operations tests
use the test database only.
"""

from __future__ import annotations

import time

import psycopg
import pytest
from fastapi.testclient import TestClient

from app.audit.verify import verify_chain
from app.core.config import get_settings
from app.db.engine import get_engine
from app.ops import seed_history
from app.pipeline.services import get_pipeline
from tests.conftest import bearer, login, scalar
from tests.test_pipeline_live import WAREHOUSE_URL, _mf_available, _run, _user, _user_with_scopes

PASSWORD = "DemoOnly-Meridian-2026"


@pytest.fixture(scope="module")
def marts(migrated_database: str) -> None:
    if not WAREHOUSE_URL or not _mf_available():
        pytest.skip("warehouse or mf not available")
    try:
        with psycopg.connect(
            WAREHOUSE_URL.replace("+psycopg", ""), connect_timeout=3
        ) as connection:
            connection.execute("SELECT 1 FROM analytics.int_data_as_of")
    except psycopg.Error:
        pytest.skip("analytics marts are not available in the warehouse")


def _token(client: TestClient, email: str) -> dict[str, str]:
    return bearer(str(login(client, email, PASSWORD)["access_token"]))


def test_overview_matches_the_chat_answer_for_the_same_period(
    client: TestClient, marts: None
) -> None:
    headers = _token(client, "executive@meridian.example")

    dashboard = client.get("/api/v1/dashboard/overview", headers=headers)

    assert dashboard.status_code == 200
    dashboard_revenue = dashboard.json()["kpis"]["revenue"]["value"]
    chat = _run(
        get_pipeline().services, "total revenue last 12 months", _user("executive@meridian.example")
    )
    assert chat["kind"] == "result"
    assert round(float(chat["rows"][0][0]), 2) == round(dashboard_revenue, 2)


def test_every_dashboard_endpoint_returns_its_sections(client: TestClient, marts: None) -> None:
    headers = _token(client, "executive@meridian.example")

    overview = client.get("/api/v1/dashboard/overview", headers=headers).json()
    sales = client.get("/api/v1/dashboard/sales", headers=headers).json()
    customers = client.get("/api/v1/dashboard/customers", headers=headers).json()
    logistics = client.get("/api/v1/dashboard/logistics", headers=headers).json()
    sellers = client.get("/api/v1/dashboard/sellers", headers=headers).json()

    assert {
        "kpis",
        "revenue_trend",
        "revenue_by_category",
        "revenue_by_state",
        "payment_mix",
    } <= set(overview)
    assert overview["revenue_trend"] and "moving_average_3m" in overview["revenue_trend"][0]
    assert len(sales["weekday_hour_heatmap"]) <= 7 * 24
    assert {"new_vs_repeat", "cohort_retention", "geography"} <= set(customers)
    assert {"delivery_days_distribution", "estimated_vs_actual", "freight_share_of_revenue"} <= set(
        logistics
    )
    assert {"top_sellers", "review_score_distribution"} <= set(sellers)


def test_category_manager_sees_only_their_categories_and_no_orders_mart(
    client: TestClient, marts: None
) -> None:
    email = _user_with_scopes("category_manager", {"categories": ["bed_bath_table"]}).email
    headers = _token(client, email)

    body = client.get("/api/v1/dashboard/overview", headers=headers).json()

    categories = {row["category"] for row in body["revenue_by_category"]["data"]}
    assert categories <= {"bed_bath_table"}
    assert body["payment_mix"]["available"] is False


def test_regional_manager_geography_is_limited_to_their_states(
    client: TestClient, marts: None
) -> None:
    email = _user_with_scopes("regional_manager", {"regions": ["RJ"]}).email
    headers = _token(client, email)

    body = client.get("/api/v1/dashboard/overview", headers=headers).json()

    assert {row["state"] for row in body["revenue_by_state"]["data"]} <= {"RJ"}


def test_admin_cannot_view_dashboards(client: TestClient, marts: None) -> None:
    response = client.get(
        "/api/v1/dashboard/overview", headers=_token(client, "admin@meridian.example")
    )

    assert response.status_code == 403


def test_etag_allows_a_not_modified_response(client: TestClient, marts: None) -> None:
    headers = _token(client, "executive@meridian.example")
    first = client.get("/api/v1/dashboard/sales", headers=headers)

    second = client.get(
        "/api/v1/dashboard/sales", headers={**headers, "If-None-Match": first.headers["ETag"]}
    )

    assert first.status_code == 200
    assert second.status_code == 304


def test_warm_dashboard_response_is_under_300_ms(client: TestClient, marts: None) -> None:
    headers = _token(client, "executive@meridian.example")
    client.get("/api/v1/dashboard/logistics", headers=headers)

    started = time.perf_counter()
    response = client.get("/api/v1/dashboard/logistics", headers=headers)
    elapsed = time.perf_counter() - started

    assert response.status_code == 200
    assert elapsed < 0.3


def test_comparison_and_filters(client: TestClient, marts: None) -> None:
    headers = _token(client, "executive@meridian.example")

    compared = client.get("/api/v1/dashboard/overview?compare=yoy", headers=headers).json()
    bad_state = client.get("/api/v1/dashboard/overview?state=S1", headers=headers)
    bad_range = client.get(
        "/api/v1/dashboard/overview?start=2018-06-01&end=2018-01-01", headers=headers
    )
    bad_compare = client.get("/api/v1/dashboard/overview?compare=sideways", headers=headers)

    assert "previous" in compared["kpis"]["revenue"]
    assert bad_state.status_code == 422
    assert bad_range.status_code == 422
    assert bad_compare.status_code == 422


def test_operations_are_admin_only_and_report_demo_data(client: TestClient) -> None:
    analyst = client.get(
        "/api/v1/admin/ops/summary", headers=_token(client, "analyst@meridian.example")
    )
    admin = client.get(
        "/api/v1/admin/ops/summary?days=30", headers=_token(client, "admin@meridian.example")
    )

    assert analyst.status_code == 403
    assert admin.status_code == 200
    body = admin.json()
    assert {
        "route_mix",
        "latency_ms",
        "failure_categories",
        "most_asked",
        "tokens_by_provider",
    } <= set(body)
    assert "demo_data" in body


def test_demo_history_is_synthetic_keeps_the_chain_and_refuses_a_second_run(
    client: TestClient,
) -> None:
    engine = get_engine(get_settings())
    before = int(scalar("SELECT count(*) FROM app.audit_log") or 0)

    seed_history.seed(engine, days=2, base_per_day=5)

    assert int(scalar("SELECT count(*) FROM app.audit_log WHERE is_synthetic") or 0) > 0
    assert int(scalar("SELECT count(*) FROM app.audit_log") or 0) > before
    assert int(scalar("SELECT count(*) FROM app.llm_usage WHERE is_synthetic") or 0) >= 0
    with engine.connect() as connection:
        assert verify_chain(connection).ok
    assert seed_history.main([]) == 1


def test_ops_summary_counts_synthetic_rows_separately(client: TestClient) -> None:
    body = client.get(
        "/api/v1/admin/ops/summary?days=90", headers=_token(client, "admin@meridian.example")
    ).json()

    assert body["synthetic_rows"] > 0
    assert body["demo_data"] is True
    assert body["cache_hit_rate"] is None or 0 <= body["cache_hit_rate"] <= 1
