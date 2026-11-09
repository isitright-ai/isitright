WITH first_ans AS (
  SELECT parent_id, MIN(creation_date) AS first_answer_date
  FROM `bigquery-public-data.stackoverflow.posts_answers`
  GROUP BY parent_id
),
daily AS (
  SELECT
    FORMAT_TIMESTAMP('%A', q.creation_date) AS day_of_week,
    COUNT(*) AS total_questions,
    COUNTIF(a.first_answer_date IS NOT NULL AND TIMESTAMP_DIFF(a.first_answer_date, q.creation_date, SECOND) BETWEEN 0 AND 3600) AS answered_within_hour
  FROM `bigquery-public-data.stackoverflow.posts_questions` q
  LEFT JOIN first_ans a ON a.parent_id = q.id
  GROUP BY day_of_week
)
SELECT
  day_of_week,
  100 * SAFE_DIVIDE(answered_within_hour, total_questions) AS pct_answered_within_hour
FROM daily
ORDER BY pct_answered_within_hour DESC
LIMIT 1 OFFSET 2