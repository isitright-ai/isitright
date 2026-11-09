WITH
q AS (
  SELECT owner_user_id AS user_id, tags
  FROM `bigquery-public-data.stackoverflow.posts_questions`
  WHERE owner_user_id BETWEEN 16712208 AND 18712208
    AND creation_date >= TIMESTAMP('2019-07-01')
    AND creation_date < TIMESTAMP('2020-01-01')
),
ans AS (
  SELECT a.owner_user_id AS user_id, pq.tags
  FROM `bigquery-public-data.stackoverflow.posts_answers` a
  JOIN `bigquery-public-data.stackoverflow.posts_questions` pq
    ON a.parent_id = pq.id
  WHERE a.owner_user_id BETWEEN 16712208 AND 18712208
    AND a.creation_date >= TIMESTAMP('2019-07-01')
    AND a.creation_date < TIMESTAMP('2020-01-01')
),
cq AS (
  SELECT c.user_id, pq.tags
  FROM `bigquery-public-data.stackoverflow.comments` c
  JOIN `bigquery-public-data.stackoverflow.posts_questions` pq
    ON c.post_id = pq.id
  WHERE c.user_id BETWEEN 16712208 AND 18712208
    AND c.creation_date >= TIMESTAMP('2019-07-01')
    AND c.creation_date < TIMESTAMP('2020-01-01')
),
ca AS (
  SELECT c.user_id, pq.tags
  FROM `bigquery-public-data.stackoverflow.comments` c
  JOIN `bigquery-public-data.stackoverflow.posts_answers` a
    ON c.post_id = a.id
  JOIN `bigquery-public-data.stackoverflow.posts_questions` pq
    ON a.parent_id = pq.id
  WHERE c.user_id BETWEEN 16712208 AND 18712208
    AND c.creation_date >= TIMESTAMP('2019-07-01')
    AND c.creation_date < TIMESTAMP('2020-01-01')
)
SELECT user_id, tags FROM q
UNION ALL
SELECT user_id, tags FROM ans
UNION ALL
SELECT user_id, tags FROM cq
UNION ALL
SELECT user_id, tags FROM ca