-- One row per order item with the order, product category and seller context joined in.
select
    items.order_id,
    items.order_item_id,
    items.product_id,
    items.seller_id,
    items.shipping_limit_at,
    items.price,
    items.freight_value,
    orders.customer_id,
    orders.customer_unique_id,
    orders.customer_state,
    orders.order_status,
    orders.is_canceled,
    orders.purchased_at,
    orders.purchase_date,
    orders.review_score,
    orders.delivered_customer_at,
    orders.delivery_days,
    orders.delay_days,
    orders.is_late,
    categories.category_name_en                 as product_category_en,
    categories.category_translation_status,
    sellers.state                               as seller_state
from {{ ref('stg_order_items') }} as items
left join {{ ref('int_orders_enriched') }} as orders
    on orders.order_id = items.order_id
left join {{ ref('int_product_categories') }} as categories
    on categories.product_id = items.product_id
left join {{ ref('stg_sellers') }} as sellers
    on sellers.seller_id = items.seller_id
