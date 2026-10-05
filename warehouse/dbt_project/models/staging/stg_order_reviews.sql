with source as (

    select * from {{ source('raw', 'order_reviews') }}

)

select
    {{ nullif_blank('review_id') }}                              as review_id,
    {{ nullif_blank('order_id') }}                               as order_id,
    {{ nullif_blank('review_score') }}::integer                  as review_score,
    {{ nullif_blank('review_comment_title') }}                   as review_comment_title,
    {{ nullif_blank('review_comment_message') }}                 as review_comment_message,
    {{ nullif_blank('review_creation_date') }}::timestamp        as review_created_at,
    {{ nullif_blank('review_answer_timestamp') }}::timestamp     as review_answered_at
from source
