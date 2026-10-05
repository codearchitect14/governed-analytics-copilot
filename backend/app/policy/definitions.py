"""Seeded roles and data policies (section 3.5 of the project plan).

Table names are schema qualified. Row filter scopes refer to keys in the user's `scopes` JSON.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.policy.engine import ANALYTICS_SCHEMA

MARTS = tuple(
    f"{ANALYTICS_SCHEMA}.{name}"
    for name in (
        "fct_order_items",
        "fct_orders",
        "dim_customers",
        "dim_products",
        "dim_sellers",
        "dim_date",
    )
)
AGGREGATES = tuple(
    f"{ANALYTICS_SCHEMA}.{name}"
    for name in (
        "agg_revenue_monthly",
        "agg_category_monthly",
        "agg_state_monthly",
        "agg_delivery_monthly",
        "agg_cohort_retention",
    )
)
ALL_ANALYTICS = MARTS + AGGREGATES


@dataclass(frozen=True)
class RoleDefinition:
    name: str
    description: str
    policy: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DemoUser:
    email: str
    full_name: str
    role: str
    scopes: dict[str, Any] = field(default_factory=dict)


ROLES: tuple[RoleDefinition, ...] = (
    RoleDefinition(
        name="executive",
        description="All rows in all marts and aggregates. No raw SQL fallback.",
        policy={
            "allowed_tables": list(ALL_ANALYTICS),
            "row_filters": {},
            "masked_columns": {},
            "max_rows": 1000,
            "allow_sql_fallback": False,
        },
    ),
    RoleDefinition(
        name="regional_manager",
        description="Rows for the states in the user's region list.",
        policy={
            "allowed_tables": [
                f"{ANALYTICS_SCHEMA}.fct_orders",
                f"{ANALYTICS_SCHEMA}.fct_order_items",
                f"{ANALYTICS_SCHEMA}.dim_customers",
                f"{ANALYTICS_SCHEMA}.dim_sellers",
                f"{ANALYTICS_SCHEMA}.dim_date",
                f"{ANALYTICS_SCHEMA}.agg_state_monthly",
                f"{ANALYTICS_SCHEMA}.agg_delivery_monthly",
            ],
            "row_filters": {
                f"{ANALYTICS_SCHEMA}.fct_orders": [
                    {"column": "customer_state", "scope": "regions"}
                ],
                f"{ANALYTICS_SCHEMA}.fct_order_items": [
                    {"column": "customer_state", "scope": "regions"}
                ],
                f"{ANALYTICS_SCHEMA}.dim_customers": [{"column": "state", "scope": "regions"}],
                f"{ANALYTICS_SCHEMA}.agg_state_monthly": [
                    {"column": "customer_state", "scope": "regions"}
                ],
            },
            "masked_columns": {},
            "max_rows": 1000,
            "allow_sql_fallback": False,
        },
    ),
    RoleDefinition(
        name="category_manager",
        description="Item rows for the product categories in the user's category list.",
        policy={
            "allowed_tables": [
                f"{ANALYTICS_SCHEMA}.fct_order_items",
                f"{ANALYTICS_SCHEMA}.dim_products",
                f"{ANALYTICS_SCHEMA}.agg_category_monthly",
            ],
            "row_filters": {
                f"{ANALYTICS_SCHEMA}.fct_order_items": [
                    {"column": "product_category_en", "scope": "categories"}
                ],
                f"{ANALYTICS_SCHEMA}.dim_products": [
                    {"column": "category_name_en", "scope": "categories"}
                ],
                f"{ANALYTICS_SCHEMA}.agg_category_monthly": [
                    {"column": "product_category_en", "scope": "categories"}
                ],
            },
            "masked_columns": {},
            "max_rows": 1000,
            "allow_sql_fallback": False,
        },
    ),
    RoleDefinition(
        name="seller_partner",
        description="Item rows and seller record for the user's own seller id only.",
        policy={
            "allowed_tables": [
                f"{ANALYTICS_SCHEMA}.fct_order_items",
                f"{ANALYTICS_SCHEMA}.dim_sellers",
            ],
            "row_filters": {
                f"{ANALYTICS_SCHEMA}.fct_order_items": [
                    {"column": "seller_id", "scope": "seller_id"}
                ],
                f"{ANALYTICS_SCHEMA}.dim_sellers": [{"column": "seller_id", "scope": "seller_id"}],
            },
            "masked_columns": {},
            "max_rows": 1000,
            "allow_sql_fallback": False,
        },
    ),
    RoleDefinition(
        name="analyst",
        description=(
            "All rows in all marts and aggregates, SQL fallback allowed, identifiers masked."
        ),
        policy={
            "allowed_tables": list(ALL_ANALYTICS),
            "row_filters": {},
            "masked_columns": {
                f"{ANALYTICS_SCHEMA}.fct_orders": ["customer_id", "customer_unique_id"],
                f"{ANALYTICS_SCHEMA}.fct_order_items": ["customer_id", "customer_unique_id"],
                f"{ANALYTICS_SCHEMA}.dim_customers": ["customer_id", "customer_unique_id"],
            },
            "max_rows": 1000,
            "allow_sql_fallback": True,
        },
    ),
    RoleDefinition(
        name="admin",
        description=(
            "User and policy management, audit access, evaluation and operations. No data tables."
        ),
        policy={
            "allowed_tables": [],
            "row_filters": {},
            "masked_columns": {},
            "max_rows": 1,
            "allow_sql_fallback": False,
        },
    ),
)

DEMO_USERS: tuple[DemoUser, ...] = (
    DemoUser("executive@meridian.example", "Executive Demo", "executive"),
    DemoUser(
        "regional.manager@meridian.example",
        "Regional Manager Demo",
        "regional_manager",
        {"regions": ["SP", "RJ", "MG", "ES"]},
    ),
    DemoUser(
        "category.manager@meridian.example",
        "Category Manager Demo",
        "category_manager",
        {"categories": ["bed_bath_table", "sports_leisure"]},
    ),
    DemoUser(
        "seller.partner@meridian.example",
        "Seller Partner Demo",
        "seller_partner",
        {"seller_id": "S1"},
    ),
    DemoUser("analyst@meridian.example", "Analyst Demo", "analyst"),
    DemoUser("admin@meridian.example", "Administrator Demo", "admin"),
)
