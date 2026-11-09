WITH snap AS (
  SELECT
    FIPS,
    SUM(SNAP_All_Participation_Households) AS total_snap_households
  FROM `bigquery-public-data.sdoh_snap_enrollment.snap_enrollment`
  WHERE Date = DATE '2017-01-01'
  GROUP BY FIPS
  HAVING SUM(SNAP_All_Participation_Households) > 0
)
SELECT
  c.geo_id AS county_geo_id,
  s.total_snap_households,
  SAFE_DIVIDE(c.income_less_10000 + c.income_10000_14999 + c.income_15000_19999, s.total_snap_households) AS low_income_to_snap_ratio
FROM snap AS s
JOIN `bigquery-public-data.census_bureau_acs.county_2017_5yr` AS c
  ON c.geo_id = s.FIPS
ORDER BY s.total_snap_households DESC
LIMIT 10