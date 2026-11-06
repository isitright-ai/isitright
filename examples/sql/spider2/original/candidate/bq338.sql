WITH j AS (
  SELECT
    a.geo_id,
    a.total_pop AS pop_2011,
    b.total_pop AS pop_2018,
    SAFE_DIVIDE(b.total_pop - a.total_pop, a.total_pop) * 100 AS pop_pct_increase,
    b.median_income - a.median_income AS income_increase
  FROM `bigquery-public-data.census_bureau_acs.censustract_2011_5yr` a
  JOIN `bigquery-public-data.census_bureau_acs.censustract_2018_5yr` b
    ON a.geo_id = b.geo_id
  WHERE STARTS_WITH(a.geo_id, '36047')
),
r AS (
  SELECT
    *,
    RANK() OVER (ORDER BY pop_pct_increase DESC) AS pop_rank,
    RANK() OVER (ORDER BY income_increase DESC) AS income_rank
  FROM j
  WHERE pop_pct_increase IS NOT NULL AND income_increase IS NOT NULL
)
SELECT
  geo_id,
  pop_2011,
  pop_2018,
  pop_pct_increase,
  income_increase
FROM r
WHERE pop_rank <= 20
  AND income_rank <= 20
  AND pop_2011 > 1000
  AND pop_2018 > 1000
ORDER BY pop_pct_increase DESC