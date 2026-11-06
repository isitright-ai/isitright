SELECT indicator_name, MAX(value) AS max_value
FROM `bigquery-public-data.world_bank_intl_debt.international_debt`
WHERE country_name = 'Russian Federation'
  AND value IS NOT NULL
  AND NOT IS_NAN(value)
GROUP BY indicator_name
ORDER BY max_value DESC
LIMIT 3