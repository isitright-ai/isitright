SELECT region
FROM (
  SELECT DISTINCT
    c.region,
    PERCENTILE_CONT(i.value, 0.5) OVER (PARTITION BY c.region) AS median_gdp
  FROM `bigquery-public-data.world_bank_wdi.indicators_data` i
  JOIN `bigquery-public-data.world_bank_wdi.country_summary` c
    ON i.country_code = c.country_code
  WHERE i.indicator_name = 'GDP (constant 2015 US$)'
    AND i.value IS NOT NULL
    AND c.region IS NOT NULL
    AND c.region != ''
)
ORDER BY median_gdp DESC
LIMIT 1