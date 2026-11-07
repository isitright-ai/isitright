WITH d AS (
  SELECT g.date, s.country, g.max, g.min, g.temp
  FROM `bigquery-public-data.noaa_gsod.gsod*` g
  JOIN `bigquery-public-data.noaa_gsod.stations` s
    ON g.stn = s.usaf AND g.wban = s.wban
  WHERE g._TABLE_SUFFIX = '2023'
    AND g.date BETWEEN DATE '2023-10-01' AND DATE '2023-10-31'
    AND s.country IN ('US', 'UK')
    AND g.max IS NOT NULL AND g.min IS NOT NULL AND g.temp IS NOT NULL
    AND g.max != 9999.9 AND g.min != 9999.9 AND g.temp != 9999.9
),
agg AS (
  SELECT
    date,
    AVG(IF(country = 'US', max, NULL)) AS us_max,
    AVG(IF(country = 'UK', max, NULL)) AS uk_max,
    AVG(IF(country = 'US', min, NULL)) AS us_min,
    AVG(IF(country = 'UK', min, NULL)) AS uk_min,
    AVG(IF(country = 'US', temp, NULL)) AS us_temp,
    AVG(IF(country = 'UK', temp, NULL)) AS uk_temp
  FROM d
  GROUP BY date
)
SELECT
  date,
  us_max - uk_max AS max_temp_diff,
  us_min - uk_min AS min_temp_diff,
  us_temp - uk_temp AS avg_temp_diff
FROM agg
ORDER BY date