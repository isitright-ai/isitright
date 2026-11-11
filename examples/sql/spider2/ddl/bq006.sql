CREATE TABLE `bigquery-public-data.austin_incidents.incidents_2016`
(
  unique_key INT64 OPTIONS(description="The unique incident number for this accident."),
  descript STRING OPTIONS(description=""),
  date DATE OPTIONS(description=""),
  time TIME OPTIONS(description=""),
  address STRING OPTIONS(description=""),
  longitude FLOAT64 OPTIONS(description=""),
  latitude FLOAT64 OPTIONS(description=""),
  location STRING OPTIONS(description="Latitude/Longitude"),
  timestamp TIMESTAMP OPTIONS(description="")
);

CREATE TABLE `bigquery-public-data.austin_incidents.incidents`
(
  unique_key INT64 OPTIONS(description="The unique incident number for this accident."),
  descript STRING OPTIONS(description=""),
  date DATE OPTIONS(description=""),
  time TIME OPTIONS(description=""),
  address STRING OPTIONS(description=""),
  longitude FLOAT64 OPTIONS(description=""),
  latitude FLOAT64 OPTIONS(description=""),
  location STRING OPTIONS(description="Latitude/Longitude"),
  timestamp TIMESTAMP OPTIONS(description="")
);
