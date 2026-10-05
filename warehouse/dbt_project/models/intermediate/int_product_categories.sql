-- One row per product with the English category name.
-- Categories without a translation fall back to the Portuguese name and are flagged.
-- Products without any category are labelled "unknown" and flagged as missing.
select
    products.product_id,
    products.category_name_pt,
    coalesce(translation.category_name_en, products.category_name_pt, 'unknown') as category_name_en,
    case
        when products.category_name_pt is null then 'missing'
        when translation.category_name_en is null then 'untranslated'
        else 'translated'
    end as category_translation_status
from {{ ref('stg_products') }} as products
left join {{ ref('stg_category_translation') }} as translation
    on translation.category_name_pt = products.category_name_pt
