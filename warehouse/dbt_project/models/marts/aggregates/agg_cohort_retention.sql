-- Monthly cohort retention. A cohort is the month of a customer's first purchase (by
-- customer_unique_id). Retention counts customers who purchased again in a later month.
with customer_orders as (

    select
        customer_unique_id,
        cast(date_trunc('month', purchased_at) as date) as activity_month
    from {{ ref('fct_orders') }}
    where not is_canceled

),

first_purchase as (

    select
        customer_unique_id,
        min(activity_month) as cohort_month
    from customer_orders
    group by customer_unique_id

),

cohort_sizes as (

    select
        cohort_month,
        count(*) as cohort_size
    from first_purchase
    group by cohort_month

),

activity as (

    select
        first_purchase.cohort_month,
        customer_orders.activity_month,
        customer_orders.customer_unique_id,
        (extract(year from customer_orders.activity_month) * 12 + extract(month from customer_orders.activity_month))
            - (extract(year from first_purchase.cohort_month) * 12 + extract(month from first_purchase.cohort_month))
            as months_since_cohort
    from customer_orders
    inner join first_purchase
        on first_purchase.customer_unique_id = customer_orders.customer_unique_id

)

select
    activity.cohort_month,
    activity.months_since_cohort::integer                    as months_since_cohort,
    cohort_sizes.cohort_size,
    count(distinct activity.customer_unique_id)              as active_customers,
    count(distinct activity.customer_unique_id)::numeric
        / nullif(cohort_sizes.cohort_size, 0)                as retention_rate
from activity
inner join cohort_sizes
    on cohort_sizes.cohort_month = activity.cohort_month
group by activity.cohort_month, activity.months_since_cohort, cohort_sizes.cohort_size
