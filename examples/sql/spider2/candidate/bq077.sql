WITH monthly AS (
  SELECT
    year,
    EXTRACT(MONTH FROM date) AS month,
    COUNT(*) AS cnt
  FROM `bigquery-public-data.chicago_crime.crime`
  WHERE primary_type = 'MOTOR VEHICLE THEFT'
    AND year BETWEEN 2010 AND 2016
  GROUP BY year, month
)
SELECT
  year,
  MAX(cnt) AS max_monthly_motor_thefts
FROM monthly
GROUP BY year
ORDER BY year