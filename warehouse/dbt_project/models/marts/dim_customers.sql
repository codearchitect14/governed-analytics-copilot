-- Grain: one row per customer_id. customer_id is per order in the source data.
-- Use customer_unique_id for customer counts and repeat rates.
select
    customer_id,
    customer_unique_id,
    zip_code_prefix,
    city,
    state
from {{ ref('stg_customers') }}
