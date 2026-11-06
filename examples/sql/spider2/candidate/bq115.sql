SELECT country_name
FROM `bigquery-public-data.census_bureau_international.midyear_population_5yr_age_sex`
WHERE year = 2017 AND total_flag = 'A'
GROUP BY country_code, country_name
ORDER BY SAFE_DIVIDE(SUM(IF(starting_age < 25, midyear_population, 0)), SUM(midyear_population)) DESC
LIMIT 1