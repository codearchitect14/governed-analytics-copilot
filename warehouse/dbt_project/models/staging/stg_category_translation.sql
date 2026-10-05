with source as (

    select * from {{ source('raw', 'product_category_name_translation') }}

)

select
    lower({{ nullif_blank('product_category_name') }})         as category_name_pt,
    lower({{ nullif_blank('product_category_name_english') }}) as category_name_en
from source
