-- Single row that defines the reference date for the dataset.
-- Olist data ends in 2018, so relative phrases such as "last month" resolve against this
-- date, not against the system clock.
select
    max(purchased_at)::date  as data_as_of_date,
    max(purchased_at)        as data_as_of_at
from {{ ref('stg_orders') }}
