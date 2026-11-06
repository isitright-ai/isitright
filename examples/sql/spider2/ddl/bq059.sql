CREATE TABLE `bigquery-public-data.san_francisco_bikeshare.bikeshare_regions`
(
  region_id INT64 NOT NULL OPTIONS(description="Unique identifier for the region"),
  name STRING NOT NULL OPTIONS(description="Public name for this region")
);

CREATE TABLE `bigquery-public-data.san_francisco_bikeshare.bikeshare_station_info`
(
  station_id STRING NOT NULL OPTIONS(description="Unique identifier of a station."),
  name STRING NOT NULL OPTIONS(description="Public name of the station"),
  short_name STRING OPTIONS(description="Short name or other type of identifier, as used by the data publisher"),
  lat FLOAT64 NOT NULL OPTIONS(description="The latitude of station. The field value must be a valid WGS 84 latitude in decimal degrees format. See: http://en.wikipedia.org/wiki/World_Geodetic_System, https://en.wikipedia.org/wiki/Decimal_degrees"),
  lon FLOAT64 NOT NULL OPTIONS(description="The longitude of station. The field value must be a valid WGS 84 longitude in decimal degrees format. See: http://en.wikipedia.org/wiki/World_Geodetic_System, https://en.wikipedia.org/wiki/Decimal_degrees"),
  region_id INT64 OPTIONS(description="ID of the region where station is located"),
  rental_methods STRING OPTIONS(description="Array of enumerables containing the payment methods accepted at this station.  Current valid values (in CAPS) are: KEY (i.e. operator issued bike key / fob / card) CREDITCARD PAYPASS APPLEPAY ANDROIDPAY TRANSITCARD ACCOUNTNUMBER PHONE This list is intended to be as comprehensive at the time of publication as possible but is subject to change, as defined in File Requirements above"),
  capacity INT64 OPTIONS(description="Number of total docking points installed at this station, both available and unavailable"),
  external_id STRING OPTIONS(description=""),
  eightd_has_key_dispenser BOOL OPTIONS(description=""),
  has_kiosk BOOL OPTIONS(description=""),
  station_geom GEOGRAPHY OPTIONS(description="")
);

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
