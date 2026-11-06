WITH all_years AS (
  SELECT 2012 AS yr, totrevenue, totfuncexpns FROM `bigquery-public-data.irs_990.irs_990_2012`
  UNION ALL
  SELECT 2013, totrevenue, totfuncexpns FROM `bigquery-public-data.irs_990.irs_990_2013`
  UNION ALL
  SELECT 2014, totrevenue, totfuncexpns FROM `bigquery-public-data.irs_990.irs_990_2014`
  UNION ALL
  SELECT 2015, totrevenue, totfuncexpns FROM `bigquery-public-data.irs_990.irs_990_2015`
  UNION ALL
  SELECT 2016, totrevenue, totfuncexpns FROM `bigquery-public-data.irs_990.irs_990_2016`
  UNION ALL
  SELECT 2017, totrevenue, totfuncexpns FROM `bigquery-public-data.irs_990.irs_990_2017`
),
medians AS (
  SELECT DISTINCT
    yr,
    PERCENTILE_CONT(totrevenue, 0.5) OVER (PARTITION BY yr) AS median_revenue,
    PERCENTILE_CONT(totfuncexpns, 0.5) OVER (PARTITION BY yr) AS median_expenses
  FROM all_years
)
SELECT
  yr AS year,
  ABS(median_revenue - median_expenses) AS abs_difference
FROM medians
ORDER BY abs_difference
LIMIT 3