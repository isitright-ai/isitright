SELECT
  state_name,
  ABS(COUNTIF(atmospheric_conditions = 1) - COUNTIF(atmospheric_conditions = 2)) AS accident_difference
FROM `bigquery-public-data.nhtsa_traffic_fatalities.accident_*`
WHERE _TABLE_SUFFIX = '2016'
  AND day_of_week IN (1, 7)
  AND atmospheric_conditions IN (1, 2)
GROUP BY state_name
ORDER BY accident_difference DESC
LIMIT 3