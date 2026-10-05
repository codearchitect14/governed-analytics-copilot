-- Delivery performance by purchase month. Only delivered orders with a delivery date count.
select
    cast(date_trunc('month', purchased_at) as date)     as month_start_date,
    count(*)                                            as delivered_orders,
    sum(case when is_late then 1 else 0 end)            as late_orders,
    avg(delivery_days)::numeric(10, 2)                  as avg_delivery_days,
    avg(delay_days)::numeric(10, 2)                     as avg_delay_days,
    (1 - avg(case when is_late then 1.0 else 0.0 end))::numeric(5, 4) as on_time_delivery_rate
from {{ ref('fct_orders') }}
where delivery_days is not null
group by 1
