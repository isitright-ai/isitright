WITH trips AS (
  SELECT s1.council_district AS district
  FROM `bigquery-public-data.austin_bikeshare.bikeshare_trips` t
  JOIN `bigquery-public-data.austin_bikeshare.bikeshare_stations` s1
    ON t.start_station_id = s1.station_id
  JOIN `bigquery-public-data.austin_bikeshare.bikeshare_stations` s2
    ON SAFE_CAST(t.end_station_id AS INT64) = s2.station_id
  WHERE s1.status = 'active'
    AND s2.status = 'active'
    AND s1.council_district = s2.council_district
    AND s1.station_id != s2.station_id
    AND s1.council_district IS NOT NULL
)
SELECT district AS council_district
FROM trips
GROUP BY district
ORDER BY COUNT(*) DESC
LIMIT 1