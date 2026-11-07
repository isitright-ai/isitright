WITH periods AS (
  SELECT
    AVG(IF(DATE(date) >= DATE '2019-01-01' AND DATE(date) < DATE '2020-01-01', SAFE_CAST(symptom_anxiety AS FLOAT64), NULL)) AS avg_anxiety_2019,
    AVG(IF(DATE(date) >= DATE '2020-01-01' AND DATE(date) < DATE '2021-01-01', SAFE_CAST(symptom_anxiety AS FLOAT64), NULL)) AS avg_anxiety_2020,
    AVG(IF(DATE(date) >= DATE '2019-01-01' AND DATE(date) < DATE '2020-01-01', SAFE_CAST(symptom_depression AS FLOAT64), NULL)) AS avg_depression_2019,
    AVG(IF(DATE(date) >= DATE '2020-01-01' AND DATE(date) < DATE '2021-01-01', SAFE_CAST(symptom_depression AS FLOAT64), NULL)) AS avg_depression_2020
  FROM `bigquery-public-data.covid19_symptom_search.symptom_search_country_weekly`
  WHERE country_region = 'United States'
    AND DATE(date) >= DATE '2019-01-01' AND DATE(date) < DATE '2021-01-01'
)
SELECT
  avg_anxiety_2019,
  avg_anxiety_2020,
  SAFE_DIVIDE(avg_anxiety_2020 - avg_anxiety_2019, avg_anxiety_2019) * 100 AS anxiety_pct_increase,
  avg_depression_2019,
  avg_depression_2020,
  SAFE_DIVIDE(avg_depression_2020 - avg_depression_2019, avg_depression_2019) * 100 AS depression_pct_increase
FROM periods