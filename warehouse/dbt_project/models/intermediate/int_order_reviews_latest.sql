-- One row per order. When an order has several reviews, the most recently answered one is kept.
select
    order_id,
    review_id,
    review_score,
    review_created_at,
    review_answered_at,
    review_comment_message is not null as has_review_comment
from (

    select
        *,
        row_number() over (
            partition by order_id
            order by review_answered_at desc nulls last, review_created_at desc nulls last, review_id
        ) as review_rank
    from {{ ref('stg_order_reviews') }}

) ranked
where review_rank = 1
