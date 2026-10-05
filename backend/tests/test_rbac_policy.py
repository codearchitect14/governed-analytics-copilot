"""Route level RBAC and the policy engine (layers 1 and 2)."""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient

from app.policy.definitions import ROLES
from app.policy.engine import PolicyDenied, build_effective_policy
from tests.conftest import bearer, login, scalar


def _policy_for(role: str) -> dict[str, object]:
    definition = next(item for item in ROLES if item.name == role)
    return dict(definition.policy)


# ---- route RBAC (layer 1) -----------------------------------------------------------------------


def test_analyst_cannot_use_admin_routes_and_the_denial_is_audited(client: TestClient) -> None:
    tokens = login(client, "analyst@meridian.example")

    response = client.get("/api/v1/admin/users", headers=bearer(str(tokens["access_token"])))

    assert response.status_code == 403
    assert (
        scalar(
            "SELECT count(*) FROM app.audit_log WHERE event = 'access_denied' "
            "AND route = '/api/v1/admin/users' AND role = 'analyst'"
        )
        >= 1
    )


def test_admin_can_list_users_and_roles(client: TestClient) -> None:
    tokens = login(client, "admin@meridian.example")
    headers = bearer(str(tokens["access_token"]))

    users = client.get("/api/v1/admin/users", headers=headers)
    roles = client.get("/api/v1/admin/roles", headers=headers)

    assert users.status_code == 200
    assert {item["email"] for item in users.json()} >= {"admin@meridian.example"}
    assert roles.status_code == 200
    assert {item["name"] for item in roles.json()} == {
        "executive",
        "regional_manager",
        "category_manager",
        "seller_partner",
        "analyst",
        "admin",
    }


def test_admin_creates_a_user_with_a_strong_password_only(client: TestClient) -> None:
    headers = bearer(str(login(client, "admin@meridian.example")["access_token"]))
    email = f"new-{uuid.uuid4().hex[:8]}@meridian.example"

    weak = client.post(
        "/api/v1/admin/users",
        headers=headers,
        json={"email": email, "full_name": "New", "password": "short", "role": "analyst"},
    )
    strong = client.post(
        "/api/v1/admin/users",
        headers=headers,
        json={
            "email": email,
            "full_name": "New",
            "password": "a-long-enough-password",
            "role": "analyst",
        },
    )
    duplicate = client.post(
        "/api/v1/admin/users",
        headers=headers,
        json={
            "email": email,
            "full_name": "New",
            "password": "a-long-enough-password",
            "role": "analyst",
        },
    )

    assert weak.status_code == 422
    assert strong.status_code == 201
    assert duplicate.status_code == 409


def test_admin_route_requires_authentication(client: TestClient) -> None:
    assert client.get("/api/v1/admin/audit/verify").status_code == 401


# ---- policy engine (layer 2) -------------------------------------------------------------------


def test_regional_manager_row_filter_uses_the_user_region_list() -> None:
    policy = build_effective_policy(
        role="regional_manager",
        policy_version=1,
        policy=_policy_for("regional_manager"),
        scopes={"regions": ["SP", "RJ"]},
    )

    filters = {
        (item.table, item.column): item.values
        for item in policy.filters_for("analytics.fct_orders")
    }

    assert filters == {("analytics.fct_orders", "customer_state"): ("SP", "RJ")}


def test_missing_scope_fails_closed_to_no_rows() -> None:
    policy = build_effective_policy(
        role="seller_partner",
        policy_version=1,
        policy=_policy_for("seller_partner"),
        scopes={},
    )

    rules = policy.filters_for("analytics.fct_order_items")

    assert rules and all(rule.is_deny_all() for rule in rules)


def test_category_manager_cannot_query_orders_mart() -> None:
    policy = build_effective_policy(
        role="category_manager",
        policy_version=1,
        policy=_policy_for("category_manager"),
        scopes={"categories": ["bed_bath_table"]},
    )

    policy.check_tables(["analytics.fct_order_items"])
    try:
        policy.check_tables(["analytics.fct_orders"])
    except PolicyDenied as denied:
        assert denied.tables == ("analytics.fct_orders",)
    else:  # pragma: no cover - the assertion above is the failure path
        raise AssertionError("fct_orders should be denied for category_manager")


def test_admin_has_no_data_tables() -> None:
    policy = build_effective_policy(
        role="admin", policy_version=1, policy=_policy_for("admin"), scopes={}
    )

    assert policy.allowed_tables == frozenset()


def test_analyst_identifiers_are_masked_and_sql_fallback_is_allowed() -> None:
    policy = build_effective_policy(
        role="analyst", policy_version=1, policy=_policy_for("analyst"), scopes={}
    )

    assert policy.allow_sql_fallback is True
    assert policy.is_masked("analytics.fct_orders", "customer_unique_id")
    assert not policy.is_masked("analytics.fct_orders", "order_status")


def test_policy_hash_is_stable_and_changes_with_scope() -> None:
    definition = _policy_for("regional_manager")
    first = build_effective_policy(
        role="regional_manager", policy_version=1, policy=definition, scopes={"regions": ["SP"]}
    )
    again = build_effective_policy(
        role="regional_manager", policy_version=1, policy=definition, scopes={"regions": ["SP"]}
    )
    other = build_effective_policy(
        role="regional_manager", policy_version=1, policy=definition, scopes={"regions": ["RJ"]}
    )

    assert first.policy_hash == again.policy_hash
    assert first.policy_hash != other.policy_hash
    assert len(first.policy_hash) == 64


def test_seeded_policies_match_the_definitions(engine) -> None:  # type: ignore[no-untyped-def]
    stored_tables = scalar(
        "SELECT allowed_tables FROM app.role_policies WHERE role = 'category_manager'"
    )

    expected = sorted(str(item) for item in _policy_for("category_manager")["allowed_tables"])  # type: ignore[index]
    assert sorted(stored_tables) == expected


def test_admin_can_disable_and_unlock_a_user(client: TestClient) -> None:
    headers = bearer(str(login(client, "admin@meridian.example")["access_token"]))
    email = f"patch-{uuid.uuid4().hex[:8]}@meridian.example"
    created = client.post(
        "/api/v1/admin/users",
        headers=headers,
        json={
            "email": email,
            "full_name": "Patch Target",
            "password": "a-long-enough-password",
            "role": "analyst",
        },
    )
    user_id = created.json()["id"]

    disabled = client.patch(
        f"/api/v1/admin/users/{user_id}", headers=headers, json={"is_active": False}
    )
    unlocked = client.patch(
        f"/api/v1/admin/users/{user_id}", headers=headers, json={"unlock": True}
    )
    missing = client.patch(
        f"/api/v1/admin/users/{uuid.uuid4()}", headers=headers, json={"is_active": True}
    )

    assert disabled.status_code == 200
    assert disabled.json()["is_active"] is False
    assert unlocked.status_code == 200
    assert missing.status_code == 404
