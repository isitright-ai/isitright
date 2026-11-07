WITH berkeley AS (
  SELECT station_id
  FROM `bigquery-public-data.san_francisco_bikeshare.bikeshare_station_info`
  WHERE region_id = 14
)
SELECT ROUND(MAX(SAFE_DIVIDE(ST_DISTANCE(t.start_station_geom, t.end_station_geom), t.duration_sec)), 1) AS highest_avg_speed_mps
FROM `bigquery-public-data.san_francisco_bikeshare.bikeshare_trips` t
JOIN berkeley s ON CAST(t.start_station_id AS STRING) = s.station_id
JOIN berkeley e ON CAST(t.end_station_id AS STRING) = e.station_id
WHERE ST_DISTANCE(t.start_station_geom, t.end_station_geom) > 1000