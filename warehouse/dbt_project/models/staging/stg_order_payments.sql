with source as (

    select * from {{ source('raw', 'order_payments') }}

)

select
    {{ nullif_blank('order_id') }}                            as order_id,
    {{ nullif_blank('payment_sequential') }}::integer          as payment_sequential,
    lower({{ nullif_blank('payment_type') }})                  as payment_type,
    {{ nullif_blank('payment_installments') }}::integer        as payment_installments,
    {{ nullif_blank('payment_value') }}::numeric(12, 2)        as payment_value
from source
