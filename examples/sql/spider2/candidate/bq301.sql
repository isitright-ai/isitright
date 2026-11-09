SELECT
  a.id AS answer_id,
  au.reputation AS answerer_reputation,
  a.score AS answer_score,
  a.comment_count AS answer_comment_count,
  q.tags AS question_tags,
  q.score AS question_score,
  q.answer_count AS question_answer_count,
  qu.reputation AS asker_reputation,
  q.view_count AS question_view_count,
  q.comment_count AS question_comment_count
FROM `bigquery-public-data.stackoverflow.posts_questions` q
JOIN `bigquery-public-data.stackoverflow.posts_answers` a
  ON a.id = q.accepted_answer_id
LEFT JOIN `bigquery-public-data.stackoverflow.users` au
  ON au.id = a.owner_user_id
LEFT JOIN `bigquery-public-data.stackoverflow.users` qu
  ON qu.id = q.owner_user_id
WHERE q.creation_date >= TIMESTAMP('2016-01-01')
  AND q.creation_date < TIMESTAMP('2016-02-01')
  AND a.creation_date >= TIMESTAMP('2016-01-01')
  AND a.creation_date < TIMESTAMP('2016-02-01')
  AND REGEXP_CONTAINS(q.tags, r'(^|\|)javascript(\||$)')
  AND (
    q.tags LIKE '%xss%'
    OR q.tags LIKE '%cross-site%'
    OR q.tags LIKE '%exploit%'
    OR q.tags LIKE '%cybersecurity%'
  )