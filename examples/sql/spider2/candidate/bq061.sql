WITH diff AS (
  SELECT
    a.geo_id,
    b.median_income - a.median_income AS income_change
  FROM `bigquery-public-data.census_bureau_acs.censustract_2015_5yr` a
  JOIN `bigquery-public-data.census_bureau_acs.censustract_2018_5yr` b
    ON a.geo_id = b.geo_id
  WHERE a.median_income IS NOT NULL
    AND b.median_income IS NOT NULL
)
SELECT c.tract_ce
FROM diff d
JOIN `bigquery-public-data.geo_census_tracts.census_tracts_california` c
  ON c.geo_id = d.geo_id
ORDER BY d.income_change DESC
LIMIT 1