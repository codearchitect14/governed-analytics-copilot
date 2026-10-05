with source as (

    select * from {{ source('raw', 'orders') }}

)

select
    {{ nullif_blank('order_id') }}                                  as order_id,
    {{ nullif_blank('customer_id') }}                               as customer_id,
    lower({{ nullif_blank('order_status') }})                       as order_status,
    {{ nullif_blank('order_purchase_timestamp') }}::timestamp       as purchased_at,
    {{ nullif_blank('order_approved_at') }}::timestamp              as approved_at,
    {{ nullif_blank('order_delivered_carrier_date') }}::timestamp   as delivered_carrier_at,
    {{ nullif_blank('order_delivered_customer_date') }}::timestamp  as delivered_customer_at,
    {{ nullif_blank('order_estimated_delivery_date') }}::timestamp  as estimated_delivery_at
from source
