WITH utah_code AS (
  SELECT DISTINCT geo_id
  FROM bigquery-public-data.geo_us_boundaries.states
  WHERE state_name = 'Utah'
),
e2000 as(
  SELECT
    AVG(month3_emplvl_23_construction) AS construction_employees_2000,
    geoid
  FROM
    (SELECT t.* EXCEPT (_shard), SUBSTR(CONCAT('2000_q', t._shard), 6) AS _TABLE_SUFFIX FROM `bigquery-public-data.bls_qcew.shards_2000_q` AS t WHERE SUBSTR(CONCAT('2000_q', t._shard), 1, 5) = '2000_')
  WHERE
    geoid LIKE CONCAT((SELECT geo_id FROM utah_code), '%')
  GROUP BY
    geoid),

e2018 AS (
  SELECT
    AVG(month3_emplvl_23_construction) AS construction_employees_2018,
    geoid,
  FROM
    (SELECT t.* EXCEPT (_shard), SUBSTR(CONCAT('2018_q', t._shard), 6) AS _TABLE_SUFFIX FROM `bigquery-public-data.bls_qcew.shards_2018_q` AS t WHERE SUBSTR(CONCAT('2018_q', t._shard), 1, 5) = '2018_') e2018
  WHERE
    geoid LIKE CONCAT((SELECT geo_id FROM utah_code), '%')
  GROUP BY
    geoid)

SELECT
  c.county_name AS county,
  (construction_employees_2018 - construction_employees_2000) / construction_employees_2000 * 100 AS increase_rate
FROM
  e2000
JOIN
  e2018 USING (geoid)
JOIN 
  `bigquery-public-data.geo_us_boundaries.counties` c ON c.geo_id = e2018.geoid
WHERE
  c.state_fips_code = (SELECT geo_id FROM utah_code)
ORDER BY
  increase_rate desc
LIMIT 1