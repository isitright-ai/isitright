WITH monthly AS (
  SELECT
    company,
    EXTRACT(MONTH FROM trip_start_timestamp) AS month,
    COUNT(*) AS trips
  FROM `bigquery-public-data.chicago_taxi_trips.taxi_trips` TABLESAMPLE SYSTEM (80 PERCENT)
  WHERE trip_start_timestamp >= TIMESTAMP '2018-01-01 00:00:00+00'
    AND trip_start_timestamp < TIMESTAMP '2019-01-01 00:00:00+00'
  GROUP BY company, month
),
diffs AS (
  SELECT
    company,
    trips - LAG(trips) OVER (PARTITION BY company ORDER BY month) AS increase
  FROM monthly
)
SELECT company
FROM diffs
WHERE increase IS NOT NULL
GROUP BY company
ORDER BY MAX(increase) DESC
LIMIT 3