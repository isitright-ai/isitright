WITH s AS (
  SELECT CAST(st.trip_id AS STRING) AS trip_id, s.stop_name, st.stop_sequence, st.arrival_time, st.departure_time
  FROM `bigquery-public-data.san_francisco_transit_muni.stop_times` st
  JOIN `bigquery-public-data.san_francisco_transit_muni.stops` s
    ON CAST(st.stop_id AS STRING) = s.stop_id
  WHERE s.stop_name IN ('Clay St & Drumm St', 'Sacramento St & Davis St')
),
pairs AS (
  SELECT a.trip_id, a.departure_time AS dep_time, b.arrival_time AS arr_time
  FROM s a
  JOIN s b
    ON a.trip_id = b.trip_id
   AND a.stop_name = 'Clay St & Drumm St'
   AND b.stop_name = 'Sacramento St & Davis St'
   AND a.stop_sequence < b.stop_sequence
)
SELECT
  t.trip_headsign,
  FORMAT_TIME('%H:%M:%S', MIN(p.dep_time)) AS earliest_departure_time,
  FORMAT_TIME('%H:%M:%S', MAX(p.arr_time)) AS latest_arrival_time
FROM pairs p
JOIN `bigquery-public-data.san_francisco_transit_muni.trips` t
  ON p.trip_id = t.trip_id
GROUP BY t.trip_headsign