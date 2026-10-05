-- One row per zip code prefix. Coordinates are the median of all source rows for that prefix.
select
    zip_code_prefix,
    percentile_cont(0.5) within group (order by lat) as lat,
    percentile_cont(0.5) within group (order by lng) as lng,
    count(*) as geolocation_row_count
from {{ ref('stg_geolocation') }}
where lat is not null
  and lng is not null
group by zip_code_prefix
