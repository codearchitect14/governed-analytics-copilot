-- Total revenue must agree across the item grain fact, the monthly aggregate and the order grain.
-- Returns one row when any of the three totals differ by more than one cent.
with item_grain as (

    select coalesce(sum(line_revenue), 0) as revenue
    from {{ ref('fct_order_items') }}
    where not coalesce(is_canceled, false)

),

monthly_aggregate as (

    select coalesce(sum(revenue), 0) as revenue
    from {{ ref('agg_revenue_monthly') }}

),

order_grain as (

    select coalesce(sum(items_total), 0) as revenue
    from {{ ref('fct_orders') }}
    where not is_canceled

)

select
    item_grain.revenue      as item_grain_revenue,
    monthly_aggregate.revenue as monthly_aggregate_revenue,
    order_grain.revenue     as order_grain_revenue
from item_grain
cross join monthly_aggregate
cross join order_grain
where abs(item_grain.revenue - monthly_aggregate.revenue) > 0.01
   or abs(item_grain.revenue - order_grain.revenue) > 0.01
