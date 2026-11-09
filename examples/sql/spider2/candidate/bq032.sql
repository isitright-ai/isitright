WITH pts AS (
  SELECT name, number, iso_time, latitude, longitude, ST_GEOGPOINT(longitude, latitude) AS p
  FROM `bigquery-public-data.noaa_hurricanes.hurricanes`
  WHERE basin = 'NA' AND EXTRACT(YEAR FROM iso_time) = 2020
),
seg AS (
  SELECT
    name, number, latitude,
    ST_DISTANCE(p, LAG(p) OVER (PARTITION BY name, number ORDER BY iso_time)) AS d,
    ROW_NUMBER() OVER (PARTITION BY name, number ORDER BY iso_time DESC) AS rn
  FROM pts
),
agg AS (
  SELECT name, number, SUM(d) AS total_dist, MAX(IF(rn = 1, latitude, NULL)) AS last_lat
  FROM seg
  GROUP BY name, number
)
SELECT last_lat AS latitude
FROM agg
ORDER BY total_dist DESC
LIMIT 1 OFFSET 1