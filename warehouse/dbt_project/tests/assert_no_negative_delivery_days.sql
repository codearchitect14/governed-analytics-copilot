-- A delivery cannot be dated before the purchase, and delivery measures must only exist for
-- delivered orders. Returns the offending orders.
select
    order_id,
    order_status,
    purchased_at,
    delivered_customer_at,
    delivery_days
from {{ ref('fct_orders') }}
where delivery_days < 0
   or (delivery_days is not null and order_status <> 'delivered')
   or (delivery_days is null and order_status = 'delivered' and delivered_customer_at is not null)
