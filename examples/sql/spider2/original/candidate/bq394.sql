WITH m AS (
  SELECT
    year,
    month,
    AVG(IF(IS_NAN(air_temperature), NULL, air_temperature)) AS a,
    AVG(IF(IS_NAN(wetbulb_temperature), NULL, wetbulb_temperature)) AS w,
    AVG(IF(IS_NAN(dewpoint_temperature), NULL, dewpoint_temperature)) AS d,
    AVG(IF(IS_NAN(sea_surface_temp), NULL, sea_surface_temp)) AS s
  FROM `bigquery-public-data.noaa_icoads.icoads_core_*`
  WHERE _TABLE_SUFFIX BETWEEN '2010' AND '2014'
  GROUP BY year, month
)
SELECT
  year,
  month,
  ABS(a - w) + ABS(a - d) + ABS(a - s) + ABS(w - d) + ABS(w - s) + ABS(d - s) AS sum_of_differences
FROM m
WHERE a IS NOT NULL AND w IS NOT NULL AND d IS NOT NULL AND s IS NOT NULL
ORDER BY sum_of_differences ASC
LIMIT 3