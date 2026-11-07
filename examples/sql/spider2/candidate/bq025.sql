WITH t AS (
  SELECT
    country_name,
    SUM(IF(total_flag = 'A' AND starting_age < 20, midyear_population, 0)) AS population_under_20,
    MAX(IF(total_flag = '*', midyear_population, NULL)) AS total_midyear_population
  FROM `bigquery-public-data.census_bureau_international.midyear_population_5yr_age_sex`
  WHERE year = 2020
  GROUP BY country_name
)
SELECT
  country_name,
  population_under_20,
  total_midyear_population,
  SAFE_DIVIDE(population_under_20, total_midyear_population) * 100 AS percent_under_20
FROM t
ORDER BY percent_under_20 DESC
LIMIT 10