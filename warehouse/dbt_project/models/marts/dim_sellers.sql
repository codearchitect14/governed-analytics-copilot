-- Grain: one row per seller.
select
    sellers.seller_id,
    sellers.zip_code_prefix,
    sellers.city,
    sellers.state,
    geo.lat,
    geo.lng
from {{ ref('stg_sellers') }} as sellers
left join {{ ref('int_geolocation_by_prefix') }} as geo
    on geo.zip_code_prefix = sellers.zip_code_prefix
