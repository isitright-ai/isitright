CREATE TABLE `bigquery-public-data.ghcn_d.ghcnd_2013`
(
  id STRING NOT NULL,
  date DATE,
  element STRING,
  value FLOAT64,
  mflag STRING,
  qflag STRING,
  sflag STRING,
  time STRING
)
OPTIONS(
  description="http://www1.ncdc.noaa.gov/pub/data/ghcn/daily/readme.txt"
);

CREATE TABLE `bigquery-public-data.ghcn_d.ghcnd_2014`
(
  id STRING NOT NULL,
  date DATE,
  element STRING,
  value FLOAT64,
  mflag STRING,
  qflag STRING,
  sflag STRING,
  time STRING
)
OPTIONS(
  description="http://www1.ncdc.noaa.gov/pub/data/ghcn/daily/readme.txt"
);

CREATE TABLE `bigquery-public-data.ghcn_d.ghcnd_2015`
(
  id STRING NOT NULL OPTIONS(description=""),
  date DATE,
  element STRING,
  value FLOAT64,
  mflag STRING,
  qflag STRING,
  sflag STRING,
  time STRING
)
OPTIONS(
  description="http://www1.ncdc.noaa.gov/pub/data/ghcn/daily/readme.txt"
);

CREATE TABLE `bigquery-public-data.ghcn_d.ghcnd_2016`
(
  id STRING NOT NULL OPTIONS(description=""),
  date DATE OPTIONS(description=""),
  element STRING OPTIONS(description=""),
  value FLOAT64 OPTIONS(description=""),
  mflag STRING OPTIONS(description=""),
  qflag STRING OPTIONS(description=""),
  sflag STRING OPTIONS(description=""),
  time STRING OPTIONS(description=""),
  source_url STRING OPTIONS(description="Source "),
  etl_timestamp TIMESTAMP OPTIONS(description="Load time for this data row")
);
