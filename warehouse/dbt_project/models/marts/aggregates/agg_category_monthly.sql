-- Monthly revenue and volume per product category (English name). Excludes canceled orders.
select
    cast(date_trunc('month', purchased_at) as date)     as month_start_date,
    product_category_en,
    count(distinct order_id)                            as orders,
    count(*)                                            as items_sold,
    sum(line_revenue)                                   as revenue
from {{ ref('fct_order_items') }}
where not coalesce(is_canceled, false)
group by 1, 2
