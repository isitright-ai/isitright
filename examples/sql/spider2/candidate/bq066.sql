WITH pov AS (
  SELECT 2016 AS birth_year, geo_id AS county_fips,
         SAFE_DIVIDE(poverty, pop_determined_poverty_status) AS poverty_rate
  FROM `bigquery-public-data.census_bureau_acs.county_2015_5yr`
  UNION ALL
  SELECT 2017 AS birth_year, geo_id AS county_fips,
         SAFE_DIVIDE(poverty, pop_determined_poverty_status) AS poverty_rate
  FROM `bigquery-public-data.census_bureau_acs.county_2016_5yr`
  UNION ALL
  SELECT 2018 AS birth_year, geo_id AS county_fips,
         SAFE_DIVIDE(poverty, pop_determined_poverty_status) AS poverty_rate
  FROM `bigquery-public-data.census_bureau_acs.county_2017_5yr`
),
nat AS (
  SELECT
    EXTRACT(YEAR FROM Year) AS birth_year,
    County_of_Residence_FIPS AS county_fips,
    SAFE_DIVIDE(SUM(IF(Maternal_Morbidity_Desc = 'None checked', Births, 0)), SUM(Births)) AS pct_no_morbidity
  FROM `bigquery-public-data.sdoh_cdc_wonder_natality.county_natality_by_maternal_morbidity`
  WHERE EXTRACT(YEAR FROM Year) BETWEEN 2016 AND 2018
  GROUP BY birth_year, county_fips
)
SELECT
  n.birth_year,
  CORR(p.poverty_rate, n.pct_no_morbidity) AS pearson_correlation
FROM nat AS n
JOIN pov AS p
  ON n.county_fips = p.county_fips
 AND n.birth_year = p.birth_year
GROUP BY n.birth_year
ORDER BY n.birth_year