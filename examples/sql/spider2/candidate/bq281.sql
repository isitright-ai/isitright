SELECT MAX(ride_count) AS max_rides
FROM (
  SELECT DATE(start_time) AS ride_date, COUNT(*) AS ride_count
  FROM `bigquery-public-data.austin_bikeshare.bikeshare_trips`
  WHERE subscriber_type = 'Student Membership'
    AND bike_type = 'electric'
    AND duration_minutes > 10
    AND start_station_name NOT IN ('Mobile Station', 'Repair Shop')
    AND end_station_name NOT IN ('Mobile Station', 'Repair Shop')
  GROUP BY ride_date
)