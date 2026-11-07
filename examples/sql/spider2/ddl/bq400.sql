CREATE TABLE `bigquery-public-data.san_francisco_transit_muni.stop_times`
(
  stop_id INT64 OPTIONS(description="Identifies the serviced stop. Multiple routes can use the same stop."),
  trip_id INT64 OPTIONS(description="Identifies a trip. Multiple trips can have the same stop"),
  stop_sequence INT64 OPTIONS(description="Identifies the order of the stops for a particular trip. The values for stop_sequence must increase throughout the trip but do not need to be consecutive."),
  arrival_time TIME OPTIONS(description="Specifies the scheduled arrival time at a specific stop for a specific trip on a route."),
  arrives_next_day BOOL OPTIONS(description="Several routes begin before midnight, with service continuing throughout the night. This variable specifies whether arrival_time occurs after midnight the day after the scheduled day.  This is useful for identifying routes that begin one day and end the next day"),
  departure_time TIME OPTIONS(description="Specifies the scheduled departure time at a specific stop for a specific trip on a route."),
  departs_next_day BOOL OPTIONS(description="Several routes begin before midnight, with service continuing throughout the night. This variable specifies whether departure_time occurs after midnight the day after the scheduled day.  This is useful for identifying routes that begin one day and end the next day"),
  dropoff_type STRING OPTIONS(description="\"Indicates whether riders are dropped off at a stop as part of the normal schedule or whether a drop off at the stop isn't available. Available options:  -  regular -  none -  phone (indicates must phone agency to arrange drop off) -  driver (indicates must coordinate with driver to arrange drop off)\""),
  exact_timepoint BOOL OPTIONS(description="Indicates if the specified arrival and departure times for a stop are strictly adhered to by the transit vehicle, or if they're instead approximate or interpolated times.")
);

CREATE TABLE `bigquery-public-data.san_francisco_transit_muni.stops`
(
  stop_id STRING OPTIONS(description="Unique identifier for each stop"),
  stop_name STRING OPTIONS(description="Full text name of the  transit stop"),
  stop_lat FLOAT64 OPTIONS(description="Latitude of the stop"),
  stop_lon FLOAT64 OPTIONS(description="Longitude of the stop"),
  stop_geom GEOGRAPHY OPTIONS(description="Geographic representation of the stop's position")
);

CREATE TABLE `bigquery-public-data.san_francisco_transit_muni.trips`
(
  trip_id STRING OPTIONS(description="Unique identifier for each trip"),
  route_id STRING OPTIONS(description="Unique identifier for each route. A single route will have multiple trips"),
  direction STRING OPTIONS(description="\"Indicates the direction of travel for a trip. The following values are valid:   -  O: Outbound travel -  I: Inbound travel  This field is not used in routing, but instead provides a way to separate trips by direction\""),
  block_id STRING OPTIONS(description="Identifies the block to which the trip belongs. A block consists of a single trip or many sequential trips made with the same vehicle. The trips are grouped into a block by the use of a shared service day andblock_id. A block_id can include trips with different service days, which then makes distinct blocks. For more details, see: https://developers.google.com/transit/gtfs/reference/#example-showing-blocks-and-service-day"),
  service_category STRING OPTIONS(description="Indicates the type of service for this trip"),
  trip_headsign STRING OPTIONS(description="Contains the text that appears on signage that identifies the trip's destination to riders. Use this field to distinguish between different patterns of service on the same route."),
  shape_id STRING OPTIONS(description="Unique identifier for the geospatial shape that describes the vehicle travel for a trip along individual points. Use to JOIN with the shapes available in the shapes table"),
  trip_shape GEOGRAPHY OPTIONS(description="Geographical representation of the trip's entire route.")
);
