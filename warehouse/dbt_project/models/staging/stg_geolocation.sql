with source as (

    select * from {{ source('raw', 'geolocation') }}

)

select
    {{ nullif_blank('geolocation_zip_code_prefix') }}        as zip_code_prefix,
    {{ nullif_blank('geolocation_lat') }}::double precision   as lat,
    {{ nullif_blank('geolocation_lng') }}::double precision   as lng,
    initcap({{ nullif_blank('geolocation_city') }})           as city,
    upper({{ nullif_blank('geolocation_state') }})            as state
from source
