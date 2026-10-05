-- Daily time spine required by MetricFlow for time based metrics and grain conversion.
select
    cast(date_day as date) as date_day
from (

    {{ dbt_utils.date_spine(
        datepart="day",
        start_date="cast('2016-01-01' as date)",
        end_date="cast('2019-01-01' as date)"
    ) }}

) as spine
