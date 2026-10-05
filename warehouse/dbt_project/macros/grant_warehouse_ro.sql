{#-
  Grants read only access on the analytics schema to the warehouse_ro role.
  Default privileges set in infra/postgres/init cover new relations; this macro also
  covers relations that already existed before the role was created.
-#}
{% macro grant_warehouse_ro() %}
  {% if execute and target.name != 'ci_skip_grants' %}
    {% do run_query('grant usage on schema ' ~ target.schema ~ ' to warehouse_ro') %}
    {% do run_query('grant select on all tables in schema ' ~ target.schema ~ ' to warehouse_ro') %}
    {{ log('Granted read access on ' ~ target.schema ~ ' to warehouse_ro', info=True) }}
  {% endif %}
{% endmacro %}
