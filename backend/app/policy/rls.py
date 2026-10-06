"""Row level security settings derived from an effective policy (layer 4).

The query API sets app.user_filters for each execution, inside the transaction that runs the
query. The database policies on the marts read it through analytics.row_visible(). The shape is:

    {"analytics.fct_orders": {"all": false, "filters": {"customer_state": ["SP", "RJ"]}},
     "analytics.dim_date":   {"all": true,  "filters": {}}}

Tables missing from the setting are not visible at all.
"""

from __future__ import annotations

from typing import Any

from app.policy.engine import EffectivePolicy


def rls_settings(policy: EffectivePolicy) -> dict[str, Any]:
    settings: dict[str, Any] = {}
    for table in sorted(policy.allowed_tables):
        filters = policy.filters_for(table)
        columns: dict[str, list[str]] = {}
        for item in filters:
            columns.setdefault(item.column, [])
            columns[item.column].extend(item.values)
        settings[table] = {
            "all": not filters,
            "filters": {column: sorted(set(values)) for column, values in sorted(columns.items())},
        }
    return settings
