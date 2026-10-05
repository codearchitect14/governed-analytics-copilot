with source as (

    select * from {{ source('raw', 'products') }}

)

select
    {{ nullif_blank('product_id') }}                             as product_id,
    lower({{ nullif_blank('product_category_name') }})           as category_name_pt,
    -- Source columns are misspelled as "lenght". Renamed here.
    {{ nullif_blank('product_name_lenght') }}::integer           as name_length,
    {{ nullif_blank('product_description_lenght') }}::integer    as description_length,
    {{ nullif_blank('product_photos_qty') }}::integer            as photos_qty,
    {{ nullif_blank('product_weight_g') }}::integer              as weight_g,
    {{ nullif_blank('product_length_cm') }}::integer             as length_cm,
    {{ nullif_blank('product_height_cm') }}::integer             as height_cm,
    {{ nullif_blank('product_width_cm') }}::integer              as width_cm
from source
