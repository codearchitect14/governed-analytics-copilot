-- Monthly revenue KPIs. Revenue is item price on orders that are not canceled.
-- GMV is item price plus freight on the same orders.
select
    cast(date_trunc('month', purchased_at) as date)     as month_start_date,
    count(distinct order_id)                            as orders,
    count(*)                                            as items_sold,
    sum(line_revenue)                                   as revenue,
    sum(line_freight)                                   as freight_revenue,
    sum(line_gmv)                                       as gmv,
    count(distinct customer_unique_id)                  as unique_customers,
    sum(line_revenue) / nullif(count(distinct order_id), 0) as avg_order_value
from {{ ref('fct_order_items') }}
where not coalesce(is_canceled, false)
group by 1
