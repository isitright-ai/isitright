CREATE TABLE `bigquery-public-data.census_bureau_international.birth_death_growth_rates`
(
  country_code STRING NOT NULL OPTIONS(description="Federal Information Processing Standard (FIPS) country/area code"),
  country_name STRING OPTIONS(description="Country or area name"),
  year INT64 NOT NULL OPTIONS(description="Year"),
  crude_birth_rate FLOAT64 OPTIONS(description="Crude birth rate (births per 1,000 population)"),
  crude_death_rate FLOAT64 OPTIONS(description="Crude death rate (deaths per 1,000 population)"),
  net_migration FLOAT64 OPTIONS(description="Net migration rate (net number of migrants per 1,000 population)"),
  rate_natural_increase FLOAT64 OPTIONS(description="Rate of natural increase (percent)"),
  growth_rate FLOAT64 OPTIONS(description="Growth rate (percent)")
)
OPTIONS(
  labels=[("freebqcovid", "")]
);

CREATE TABLE `bigquery-public-data.census_bureau_international.country_names_area`
(
  country_code STRING NOT NULL OPTIONS(description="Federal Information Processing Standard (FIPS) country/area code"),
  country_name STRING OPTIONS(description="Country or area name"),
  country_area FLOAT64 OPTIONS(description="Area in square kilometers")
)
OPTIONS(
  labels=[("freebqcovid", "")]
);
