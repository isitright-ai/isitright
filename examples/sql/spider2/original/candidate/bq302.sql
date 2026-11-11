SELECT
  FORMAT_TIMESTAMP('%Y-%m', creation_date) AS month,
  COUNTIF('python' IN UNNEST(SPLIT(tags, '|'))) AS python_questions,
  COUNT(*) AS total_questions,
  SAFE_DIVIDE(COUNTIF('python' IN UNNEST(SPLIT(tags, '|'))), COUNT(*)) AS python_proportion
FROM `bigquery-public-data.stackoverflow.posts_questions`
WHERE creation_date >= TIMESTAMP('2022-01-01')
  AND creation_date < TIMESTAMP('2023-01-01')
GROUP BY month
ORDER BY month