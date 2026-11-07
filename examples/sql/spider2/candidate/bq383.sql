SELECT
  EXTRACT(YEAR FROM date) AS year,
  MAX(IF(element = 'PRCP', value / 10, NULL)) AS max_prcp_mm,
  MAX(IF(element = 'TMIN', value / 10, NULL)) AS max_tmin_c,
  MAX(IF(element = 'TMAX', value / 10, NULL)) AS max_tmax_c
FROM `bigquery-public-data.ghcn_d.ghcnd_*`
WHERE _TABLE_SUFFIX BETWEEN '2013' AND '2016'
  AND id = 'USW00094846'
  AND element IN ('PRCP', 'TMIN', 'TMAX')
  AND value IS NOT NULL
  AND qflag IS NULL
  AND EXTRACT(MONTH FROM date) = 12
  AND EXTRACT(DAY FROM date) >= 17
GROUP BY year
ORDER BY year