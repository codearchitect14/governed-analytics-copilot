"""Integration test: every plan fixture compiles through MetricFlow and matches its gold SQL.

Requires a running database with the analytics marts built, and WAREHOUSE_RO_DATABASE_URL.
The test is skipped when either is missing, so unit test runs stay offline.
"""

from __future__ import annotations

import os

import pytest
from semantic import golden

pytestmark = pytest.mark.integration
EXPECTED_PLAN_COUNT = 30


@pytest.fixture(scope="module")
def database_url() -> str:
    url = os.environ.get("WAREHOUSE_RO_DATABASE_URL", "")
    if not url:
        pytest.skip("WAREHOUSE_RO_DATABASE_URL is not set")
    return url


def test_fixture_file_has_thirty_plans() -> None:
    assert len(golden.load_fixtures()) == EXPECTED_PLAN_COUNT


def test_all_plans_match_gold_results(database_url: str) -> None:
    results = golden.run_all(database_url)

    failures = [f"{r.fixture_id}: {r.message} {r.details}" for r in results if not r.matched]
    assert not failures, "\n".join(failures)
