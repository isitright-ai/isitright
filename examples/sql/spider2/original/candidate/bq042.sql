SELECT
  year,
  temp,
  SAFE_CAST(wdsp AS FLOAT64) AS wdsp,
  prcp
FROM `bigquery-public-data.noaa_gsod.gsod*`
WHERE _TABLE_SUFFIX BETWEEN '2011' AND '2020'
  AND stn = '725030'
  AND mo = '06'
  AND da = '12'
ORDER BY year