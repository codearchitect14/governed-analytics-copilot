-- Grain: one row per order item.
-- Customer state, seller id and product category are denormalized so that every row filter
-- is a single table predicate in the policy engine.
select
    order_id || '-' || order_item_id::text    as order_item_key,
    order_id,
    order_item_id,
    product_id,
    seller_id,
    seller_state,
    customer_id,
    customer_unique_id,
    customer_state,
    product_category_en,
    category_translation_status,
    order_status,
    is_canceled,
    purchased_at,
    purchase_date                       as purchase_date_key,
    price                               as line_revenue,
    freight_value                       as line_freight,
    price + freight_value               as line_gmv,
    review_score,
    delivered_customer_at,
    delivery_days,
    delay_days,
    is_late,
    shipping_limit_at
from {{ ref('int_order_items_enriched') }}
