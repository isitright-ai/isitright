SELECT MAX(answer_count) AS max_answer_count
FROM `bigquery-public-data.stackoverflow.posts_questions`
WHERE REGEXP_CONTAINS(tags, r'(^|\|)python-2')
  AND NOT REGEXP_CONTAINS(tags, r'(^|\|)python-3')