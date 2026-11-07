CREATE TABLE `bigquery-public-data.census_bureau_international.midyear_population`
(
  country_code STRING NOT NULL OPTIONS(description="Federal Information Processing Standard (FIPS) country/area code"),
  country_name STRING OPTIONS(description="Country or area name"),
  year INT64 NOT NULL OPTIONS(description="Year"),
  midyear_population INT64 OPTIONS(description="Both sexes midyear population")
)
OPTIONS(
  labels=[("freebqcovid", "")]
);

CREATE TABLE `bigquery-public-data.census_bureau_international.midyear_population_5yr_age_sex`
(
  country_code STRING NOT NULL OPTIONS(description="Federal Information Processing Standard (FIPS) country/area code"),
  country_name STRING OPTIONS(description="Country or area name"),
  year INT64 NOT NULL OPTIONS(description="Year"),
  total_flag STRING OPTIONS(description="Total flag: \"*\"=Total, all ages; \"A\"=Individual age group"),
  starting_age INT64 OPTIONS(description="Starting age (0 to 100)"),
  age_group_indicator STRING OPTIONS(description="Age group indicator: \"-\"=5-year age group; \"+\"=open-ended age group"),
  ending_age INT64 OPTIONS(description="Ending age (4 to 99; set to 0 if G=\"+\")"),
  midyear_population INT64 OPTIONS(description="Both sexes midyear population in the age group"),
  midyear_population_male INT64 OPTIONS(description="Male midyear population in the age group"),
  midyear_population_female INT64 OPTIONS(description="Female midyear population in the age group")
)
OPTIONS(
  labels=[("freebqcovid", "")]
);

CREATE TABLE `bigquery-public-data.census_bureau_international.midyear_population_agespecific`
(
  country_code STRING NOT NULL OPTIONS(description="Federal Information Processing Standard (FIPS) country/area code"),
  country_name STRING OPTIONS(description="Country or area name"),
  year INT64 NOT NULL OPTIONS(description="Year"),
  sex STRING OPTIONS(description="Gender"),
  population INT64 OPTIONS(description="Total count of individuals"),
  age INT64 OPTIONS(description="Age in years")
)
OPTIONS(
  labels=[("freebqcovid", "")]
);
