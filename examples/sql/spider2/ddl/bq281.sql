CREATE TABLE `bigquery-public-data.austin_bikeshare.bikeshare_trips`
(
  trip_id STRING OPTIONS(description="Numeric ID of bike trip"),
  subscriber_type STRING OPTIONS(description="Type of the Subscriber"),
  bike_id STRING OPTIONS(description="ID of bike used"),
  bike_type STRING OPTIONS(description="Type of bike used"),
  start_time TIMESTAMP OPTIONS(description="Start timestamp of trip"),
  start_station_id INT64 OPTIONS(description="Numeric reference for start station"),
  start_station_name STRING OPTIONS(description="Station name for start station"),
  end_station_id STRING OPTIONS(description="Numeric reference for end station"),
  end_station_name STRING OPTIONS(description="Station name for end station"),
  duration_minutes INT64 OPTIONS(description="Time of trip in minutes")
);
