WITH t AS (
  SELECT
    r.name AS region_name,
    tr.trip_id,
    tr.duration_sec,
    tr.start_date,
    tr.start_station_name,
    tr.member_gender,
    ROW_NUMBER() OVER (PARTITION BY r.region_id ORDER BY tr.start_date DESC) AS rn
  FROM `bigquery-public-data.san_francisco_bikeshare.bikeshare_trips` tr
  JOIN `bigquery-public-data.san_francisco_bikeshare.bikeshare_station_info` si
    ON CAST(tr.start_station_id AS STRING) = si.station_id
  JOIN `bigquery-public-data.san_francisco_bikeshare.bikeshare_regions` r
    ON si.region_id = r.region_id
  WHERE EXTRACT(YEAR FROM tr.start_date) BETWEEN 2014 AND 2017
)
SELECT
  region_name,
  trip_id,
  duration_sec,
  start_date,
  start_station_name,
  member_gender
FROM t
WHERE rn = 1