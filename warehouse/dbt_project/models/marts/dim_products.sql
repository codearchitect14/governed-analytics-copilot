-- Grain: one row per product.
select
    products.product_id,
    categories.category_name_en,
    categories.category_name_pt,
    categories.category_translation_status,
    products.name_length,
    products.description_length,
    products.photos_qty,
    products.weight_g,
    products.length_cm,
    products.height_cm,
    products.width_cm
from {{ ref('stg_products') }} as products
left join {{ ref('int_product_categories') }} as categories
    on categories.product_id = products.product_id
