WITH y2000 AS (
  SELECT area_fips, AVG(month3_emplvl_23_construction) AS avg_emp_2000
  FROM `bigquery-public-data.bls_qcew.2000_q*`
  WHERE area_fips LIKE '49%'
  GROUP BY area_fips
),
y2018 AS (
  SELECT area_fips, AVG(month3_emplvl_23_construction) AS avg_emp_2018
  FROM `bigquery-public-data.bls_qcew.2018_q*`
  WHERE area_fips LIKE '49%'
  GROUP BY area_fips
)
SELECT
  c.county_name,
  SAFE_DIVIDE(b.avg_emp_2018 - a.avg_emp_2000, a.avg_emp_2000) * 100 AS pct_increase
FROM y2000 a
JOIN y2018 b ON a.area_fips = b.area_fips
JOIN `bigquery-public-data.geo_us_boundaries.counties` c
  ON c.county_fips_code = a.area_fips AND c.state_fips_code = '49'
WHERE a.avg_emp_2000 > 0
ORDER BY pct_increase DESC
LIMIT 1