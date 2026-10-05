-- Monthly revenue and orders per customer state. Excludes canceled orders.
select
    cast(date_trunc('month', purchased_at) as date)     as month_start_date,
    customer_state,
    count(distinct order_id)                            as orders,
    count(distinct customer_unique_id)                  as unique_customers,
    sum(line_revenue)                                   as revenue
from {{ ref('fct_order_items') }}
where not coalesce(is_canceled, false)
group by 1, 2
