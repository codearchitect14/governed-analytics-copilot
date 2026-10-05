with source as (

    select * from {{ source('raw', 'customers') }}

)

select
    {{ nullif_blank('customer_id') }}                       as customer_id,
    {{ nullif_blank('customer_unique_id') }}                as customer_unique_id,
    {{ nullif_blank('customer_zip_code_prefix') }}          as zip_code_prefix,
    initcap({{ nullif_blank('customer_city') }})            as city,
    upper({{ nullif_blank('customer_state') }})             as state
from source
