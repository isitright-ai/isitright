SELECT
  category,
  COUNT(*) AS total_articles,
  100 * SAFE_DIVIDE(COUNTIF(REGEXP_CONTAINS(LOWER(body), r'education')), COUNT(*)) AS percentage_mentioning_education
FROM `bigquery-public-data.bbc_news.fulltext`
GROUP BY category