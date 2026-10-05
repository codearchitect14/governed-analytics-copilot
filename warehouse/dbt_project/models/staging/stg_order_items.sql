with source as (

    select * from {{ source('raw', 'order_items') }}

)

select
    {{ nullif_blank('order_id') }}                          as order_id,
    {{ nullif_blank('order_item_id') }}::integer            as order_item_id,
    {{ nullif_blank('product_id') }}                        as product_id,
    {{ nullif_blank('seller_id') }}                         as seller_id,
    {{ nullif_blank('shipping_limit_date') }}::timestamp    as shipping_limit_at,
    {{ nullif_blank('price') }}::numeric(12, 2)             as price,
    {{ nullif_blank('freight_value') }}::numeric(12, 2)     as freight_value
from source
