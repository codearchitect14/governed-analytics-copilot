-- One row per order with customer attributes, item and payment totals, review score and
-- delivery measures. Delivery measures are only computed for delivered orders.
with items as (

    select
        order_id,
        count(*)                        as items_count,
        count(distinct seller_id)       as sellers_count,
        sum(price)                      as items_total,
        sum(freight_value)              as freight_total
    from {{ ref('stg_order_items') }}
    group by order_id

),

orders as (

    select
        orders.order_id,
        orders.customer_id,
        customers.customer_unique_id,
        customers.state                             as customer_state,
        customers.city                              as customer_city,
        orders.order_status,
        orders.order_status = 'canceled'            as is_canceled,
        orders.purchased_at,
        orders.purchased_at::date                   as purchase_date,
        orders.delivered_customer_at,
        orders.estimated_delivery_at
    from {{ ref('stg_orders') }} as orders
    left join {{ ref('stg_customers') }} as customers
        on customers.customer_id = orders.customer_id

)

select
    orders.order_id,
    orders.customer_id,
    orders.customer_unique_id,
    orders.customer_state,
    orders.customer_city,
    orders.order_status,
    orders.is_canceled,
    orders.purchased_at,
    orders.purchase_date,
    coalesce(items.items_count, 0)                  as items_count,
    coalesce(items.sellers_count, 0)                as sellers_count,
    coalesce(items.items_total, 0)                  as items_total,
    coalesce(items.freight_total, 0)                as freight_total,
    payments.payment_total,
    payments.payment_installments_max,
    payments.payment_type_primary,
    payments.payment_methods_count,
    reviews.review_score,
    orders.delivered_customer_at,
    orders.estimated_delivery_at,

    -- Delivery measures: only for delivered orders with a delivery timestamp
    case
        when orders.order_status = 'delivered' and orders.delivered_customer_at is not null
        then orders.delivered_customer_at::date - orders.purchase_date
    end as delivery_days,

    case
        when orders.order_status = 'delivered'
            and orders.delivered_customer_at is not null
            and orders.estimated_delivery_at is not null
        then orders.delivered_customer_at::date - orders.estimated_delivery_at::date
    end as delay_days,

    case
        when orders.order_status = 'delivered'
            and orders.delivered_customer_at is not null
            and orders.estimated_delivery_at is not null
        then orders.delivered_customer_at::date > orders.estimated_delivery_at::date
    end as is_late

from orders
left join items
    on items.order_id = orders.order_id
left join {{ ref('int_order_payments_by_order') }} as payments
    on payments.order_id = orders.order_id
left join {{ ref('int_order_reviews_latest') }} as reviews
    on reviews.order_id = orders.order_id
