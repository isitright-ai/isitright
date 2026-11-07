SELECT
  EXTRACT(YEAR FROM t.start_time) AS year,
  s.status AS status,
  COUNT(DISTINCT s.station_id) AS station_count
FROM `bigquery-public-data.austin_bikeshare.bikeshare_trips` AS t
JOIN `bigquery-public-data.austin_bikeshare.bikeshare_stations` AS s
  ON t.start_station_id = s.station_id
WHERE EXTRACT(YEAR FROM t.start_time) IN (2013, 2014)
  AND s.status IN ('active', 'closed')
GROUP BY year, status
ORDER BY year, status