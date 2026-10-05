-- Grain: one row per order.
with base as (

    select * from {{ ref('int_orders_enriched') }}

)

select
    order_id,
    customer_id,
    customer_unique_id,
    customer_state,
    customer_city,
    order_status,
    is_canceled,
    purchased_at,
    purchase_date                       as purchase_date_key,
    items_count,
    sellers_count,
    items_total,
    freight_total,
    payment_total,
    payment_installments_max,
    payment_methods_count,
    payment_type_primary,
    review_score,
    delivered_customer_at,
    estimated_delivery_at,
    delivery_days,
    delay_days,
    is_late,
    case
        when delivery_days is null then 'not_delivered'
        when is_late then 'late'
        else 'on_time'
    end                                 as delivery_status,
    -- Position of each non canceled order in the customer's purchase history (1 = first)
    case
        when is_canceled then null
        else row_number() over (
            partition by customer_unique_id, is_canceled
            order by purchased_at, order_id
        )
    end                                 as customer_order_seq
from base
