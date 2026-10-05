-- Grain: one row per calendar day covering the full Olist range (2016 to 2018).
with spine as (

    {{ dbt_utils.date_spine(
        datepart="day",
        start_date="cast('2016-01-01' as date)",
        end_date="cast('2019-01-01' as date)"
    ) }}

)

select
    cast(date_day as date)                              as date_key,
    extract(year from date_day)::integer                as year,
    extract(quarter from date_day)::integer             as quarter,
    extract(month from date_day)::integer               as month,
    to_char(date_day, 'YYYY-MM')                        as year_month,
    cast(date_trunc('month', date_day) as date)         as month_start_date,
    cast(date_trunc('week', date_day) as date)          as week_start_date,
    extract(isodow from date_day)::integer              as iso_day_of_week,
    extract(isodow from date_day) in (6, 7)             as is_weekend
from spine
