CREATE TABLE `bigquery-public-data.san_francisco_bikeshare.bikeshare_trips`
(
  trip_id STRING NOT NULL OPTIONS(description="Numeric ID of bike trip"),
  duration_sec INT64 OPTIONS(description="Time of trip in seconds"),
  start_date TIMESTAMP OPTIONS(description="Start date of trip with date and time, in PST"),
  start_station_name STRING OPTIONS(description="Station name of start station"),
  start_station_id INT64 OPTIONS(description="Numeric reference for start station"),
  end_date TIMESTAMP OPTIONS(description="End date of trip with date and time, in PST"),
  end_station_name STRING OPTIONS(description="Station name for end station"),
  end_station_id INT64 OPTIONS(description="Numeric reference for end station"),
  bike_number INT64 OPTIONS(description="ID of bike used"),
  zip_code STRING OPTIONS(description="Home zip code of subscriber (customers can choose to manually enter zip at kiosk however data is unreliable)"),
  subscriber_type STRING OPTIONS(description="Subscriber = annual or 30-day member; Customer = 24-hour or 3-day member"),
  c_subscription_type STRING OPTIONS(description=""),
  start_station_latitude FLOAT64 OPTIONS(description=""),
  start_station_longitude FLOAT64 OPTIONS(description=""),
  end_station_latitude FLOAT64 OPTIONS(description=""),
  end_station_longitude FLOAT64 OPTIONS(description=""),
  member_birth_year INT64 OPTIONS(description=""),
  member_gender STRING OPTIONS(description=""),
  bike_share_for_all_trip STRING OPTIONS(description=""),
  start_station_geom GEOGRAPHY OPTIONS(description=""),
  end_station_geom GEOGRAPHY OPTIONS(description="")
);
