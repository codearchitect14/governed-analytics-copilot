with source as (

    select * from {{ source('raw', 'sellers') }}

)

select
    {{ nullif_blank('seller_id') }}                       as seller_id,
    {{ nullif_blank('seller_zip_code_prefix') }}          as zip_code_prefix,
    initcap({{ nullif_blank('seller_city') }})            as city,
    upper({{ nullif_blank('seller_state') }})             as state
from source
