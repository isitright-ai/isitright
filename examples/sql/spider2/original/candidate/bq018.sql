WITH d AS (
  SELECT
    date,
    cumulative_confirmed,
    LAG(cumulative_confirmed) OVER (ORDER BY date) AS prev_cum
  FROM `bigquery-public-data.covid19_open_data.covid19_open_data`
  WHERE location_key = 'US'
    AND date BETWEEN DATE '2020-02-29' AND DATE '2020-04-30'
)
SELECT FORMAT_DATE('%m-%d', date) AS day
FROM d
WHERE date >= DATE '2020-03-01'
ORDER BY SAFE_DIVIDE(cumulative_confirmed - prev_cum, prev_cum) DESC
LIMIT 1