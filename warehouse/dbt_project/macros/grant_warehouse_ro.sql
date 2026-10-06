{#-
  Runs after every dbt command (on-run-end).

  1. Read access for warehouse_ro is limited to marts, aggregates, the MetricFlow time spine and
     the data reference date. Staging and intermediate views are not readable by the executor:
     views run with their owner's rights and would bypass row level security.
  2. Row level security (layer 4 of the authorization model). Each mart table gets a policy that
     calls analytics.row_visible(), which reads the per transaction setting app.user_filters that
     the query API sets for each request. With no setting, or with no entry for the table, no row
     is visible (fail closed).
-#}
{% macro grant_warehouse_ro() %}
  {% if execute %}

    {% set fn_sql %}
CREATE OR REPLACE FUNCTION analytics.row_visible(tbl text, key_values jsonb)
RETURNS boolean
LANGUAGE plpgsql
STABLE
AS $fn$
DECLARE
  settings jsonb;
  cfg jsonb;
  filters jsonb;
  column_name text;
  value text;
BEGIN
  settings := nullif(current_setting('app.user_filters', true), '')::jsonb;
  IF settings IS NULL THEN
    RETURN false;
  END IF;
  cfg := settings -> tbl;
  IF cfg IS NULL THEN
    RETURN false;
  END IF;
  IF (cfg ->> 'all') = 'true' THEN
    RETURN true;
  END IF;
  filters := coalesce(cfg -> 'filters', '{}'::jsonb);
  FOR column_name IN SELECT jsonb_object_keys(filters) LOOP
    value := key_values ->> column_name;
    IF value IS NULL OR NOT EXISTS (
      SELECT 1 FROM jsonb_array_elements_text(filters -> column_name) AS allowed(v) WHERE allowed.v = value
    ) THEN
      RETURN false;
    END IF;
  END LOOP;
  RETURN true;
END
$fn$
    {% endset %}
    {% do run_query(fn_sql) %}

    {% set rls_policies = {
      'fct_orders': "jsonb_build_object('customer_state', customer_state)",
      'fct_order_items': "jsonb_build_object('customer_state', customer_state, 'product_category_en', product_category_en, 'seller_id', seller_id)",
      'dim_customers': "jsonb_build_object('state', state)",
      'dim_products': "jsonb_build_object('category_name_en', category_name_en)",
      'dim_sellers': "jsonb_build_object('seller_id', seller_id)",
      'agg_state_monthly': "jsonb_build_object('customer_state', customer_state)",
      'agg_category_monthly': "jsonb_build_object('product_category_en', product_category_en)",
      'agg_revenue_monthly': "'{}'::jsonb",
      'agg_delivery_monthly': "'{}'::jsonb",
      'agg_cohort_retention': "'{}'::jsonb",
      'dim_date': "'{}'::jsonb"
    } %}

    {% set readable = [
      'fct_orders', 'fct_order_items', 'dim_customers', 'dim_products', 'dim_sellers', 'dim_date',
      'agg_revenue_monthly', 'agg_category_monthly', 'agg_state_monthly', 'agg_delivery_monthly',
      'agg_cohort_retention', 'metricflow_time_spine', 'int_data_as_of'
    ] %}

    {% do run_query('revoke select on all tables in schema ' ~ target.schema ~ ' from warehouse_ro') %}
    {% do run_query('grant usage on schema ' ~ target.schema ~ ' to warehouse_ro') %}
    {% for name in readable | unique %}
      {% do run_query('grant select on ' ~ target.schema ~ '.' ~ name ~ ' to warehouse_ro') %}
    {% endfor %}

    {% for name, key_expr in rls_policies.items() %}
      {% do run_query('alter table ' ~ target.schema ~ '.' ~ name ~ ' enable row level security') %}
      {% do run_query('drop policy if exists warehouse_ro_rls on ' ~ target.schema ~ '.' ~ name) %}
      {% do run_query(
        'create policy warehouse_ro_rls on ' ~ target.schema ~ '.' ~ name
        ~ ' for select to warehouse_ro using (analytics.row_visible(\'' ~ target.schema ~ '.' ~ name ~ '\', ' ~ key_expr ~ '))'
      ) %}
    {% endfor %}

    {{ log('Read access and row level security applied for warehouse_ro', info=True) }}
  {% endif %}
{% endmacro %}
