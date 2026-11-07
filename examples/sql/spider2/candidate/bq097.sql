WITH y AS (
  SELECT
    GeoName,
    EXTRACT(YEAR FROM Year) AS yr,
    Earnings_per_job_avg
  FROM `bigquery-public-data.sdoh_bea_cainc30.fips`
  WHERE GeoName LIKE '%, MA'
    AND EXTRACT(YEAR FROM Year) IN (2012, 2017)
)
SELECT
  GeoName,
  MAX(IF(yr = 2017, Earnings_per_job_avg, NULL)) - MAX(IF(yr = 2012, Earnings_per_job_avg, NULL)) AS earnings_per_job_increase
FROM y
GROUP BY GeoName
HAVING COUNT(DISTINCT yr) = 2
ORDER BY earnings_per_job_increase DESC