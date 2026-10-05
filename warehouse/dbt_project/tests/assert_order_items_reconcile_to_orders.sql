-- Reconciliation between grains: for every order, the item count and the sum of item prices in
-- fct_order_items must equal the order level totals in fct_orders.
-- Returns one row per mismatching order, so the test fails when any row is returned.
with item_totals as (

    select
        order_id,
        count(*)            as item_count,
        sum(line_revenue)   as item_price_total
    from {{ ref('fct_order_items') }}
    group by order_id

)

select
    orders.order_id,
    orders.items_count,
    item_totals.item_count,
    orders.items_total,
    item_totals.item_price_total
from {{ ref('fct_orders') }} as orders
left join item_totals
    on item_totals.order_id = orders.order_id
where coalesce(orders.items_count, 0) <> coalesce(item_totals.item_count, 0)
   or abs(coalesce(orders.items_total, 0) - coalesce(item_totals.item_price_total, 0)) > 0.01
