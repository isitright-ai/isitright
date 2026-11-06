WITH rain AS (
  SELECT
    stn,
    wban,
    COUNTIF(_TABLE_SUFFIX = '2023' AND prcp > 0) AS rainy_days_2023,
    COUNTIF(_TABLE_SUFFIX = '2022' AND prcp > 0) AS rainy_days_2022
  FROM `bigquery-public-data.noaa_gsod.gsod*`
  WHERE _TABLE_SUFFIX IN ('2022', '2023')
    AND prcp IS NOT NULL
    AND prcp != 99.99
  GROUP BY stn, wban
)
SELECT
  s.usaf,
  s.wban,
  s.name,
  r.rainy_days_2023,
  r.rainy_days_2022
FROM rain AS r
JOIN `bigquery-public-data.noaa_gsod.stations` AS s
  ON s.usaf = r.stn AND s.wban = r.wban
WHERE s.state = 'WA'
  AND s.country = 'US'
  AND r.rainy_days_2023 > 150
  AND r.rainy_days_2023 < r.rainy_days_2022