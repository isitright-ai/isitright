WITH pts AS (
  SELECT
    sid,
    name,
    iso_time,
    latitude,
    longitude,
    usa_wind,
    ST_GEOGPOINT(longitude, latitude) AS pt
  FROM `bigquery-public-data.noaa_hurricanes.hurricanes`
  WHERE season = '2020'
    AND basin = 'NA'
    AND latitude IS NOT NULL
    AND longitude IS NOT NULL
),
seg AS (
  SELECT
    *,
    IFNULL(ST_DISTANCE(pt, LAG(pt) OVER (PARTITION BY sid ORDER BY iso_time)), 0) / 1000 AS seg_km
  FROM pts
),
cum AS (
  SELECT
    *,
    SUM(seg_km) OVER (PARTITION BY sid ORDER BY iso_time ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS cumulative_km
  FROM seg
),
totals AS (
  SELECT sid, SUM(seg_km) AS total_km
  FROM seg
  GROUP BY sid
),
ranked AS (
  SELECT sid, total_km, RANK() OVER (ORDER BY total_km DESC) AS rnk
  FROM totals
)
SELECT
  c.name,
  c.iso_time,
  c.latitude,
  c.longitude,
  c.cumulative_km,
  c.usa_wind AS max_sustained_wind_speed
FROM cum c
JOIN ranked r ON c.sid = r.sid
WHERE r.rnk = 3
ORDER BY c.iso_time