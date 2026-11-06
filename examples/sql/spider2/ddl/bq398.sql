CREATE TABLE `bigquery-public-data.world_bank_intl_debt.international_debt`
(
  country_name STRING OPTIONS(description=""),
  country_code STRING OPTIONS(description=""),
  indicator_name STRING OPTIONS(description=""),
  indicator_code STRING OPTIONS(description=""),
  value FLOAT64 OPTIONS(description=""),
  year INT64 OPTIONS(description="")
);
