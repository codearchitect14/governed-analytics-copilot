-- One row per order. An order can have several payments (installments, vouchers).
-- The primary payment type is the type with the largest payment value.
with totals as (

    select
        order_id,
        sum(payment_value)              as payment_total,
        max(payment_installments)       as payment_installments_max,
        count(*)                        as payment_rows,
        count(distinct payment_type)    as payment_methods_count
    from {{ ref('stg_order_payments') }}
    group by order_id

),

ranked as (

    select
        order_id,
        payment_type,
        row_number() over (
            partition by order_id
            order by payment_value desc, payment_sequential
        ) as payment_rank
    from {{ ref('stg_order_payments') }}

)

select
    totals.order_id,
    totals.payment_total,
    totals.payment_installments_max,
    totals.payment_rows,
    totals.payment_methods_count,
    ranked.payment_type as payment_type_primary
from totals
left join ranked
    on ranked.order_id = totals.order_id
    and ranked.payment_rank = 1
