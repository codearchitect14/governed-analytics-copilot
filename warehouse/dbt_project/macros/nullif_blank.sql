{#- Treat empty or whitespace only CSV values as NULL. Raw Olist columns are loaded as text. -#}
{% macro nullif_blank(column_name) -%}
  nullif(trim({{ column_name }}), '')
{%- endmacro %}
