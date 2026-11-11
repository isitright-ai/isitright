WITH epa AS (
  SELECT ROUND(latitude, 2) AS lat, ROUND(longitude, 2) AS lon, AVG(arithmetic_mean) AS epa_avg
  FROM `bigquery-public-data.epa_historical_air_quality.pm25_nonfrm_daily_summary`
  WHERE EXTRACT(YEAR FROM date_local) = 1990
    AND units_of_measure = 'Micrograms/cubic meter (LC)'
    AND parameter_name = 'Acceptable PM2.5 AQI & Speciation Mass'
  GROUP BY lat, lon
),
oaq AS (
  SELECT city, ROUND(latitude, 2) AS lat, ROUND(longitude, 2) AS lon, AVG(value) AS oaq_avg
  FROM `bigquery-public-data.openaq.global_air_quality`
  WHERE pollutant = 'pm25'
    AND EXTRACT(YEAR FROM timestamp) = 2020
  GROUP BY city, lat, lon
)
SELECT oaq.city
FROM oaq
JOIN epa
  ON oaq.lat = epa.lat AND oaq.lon = epa.lon
GROUP BY oaq.city
ORDER BY AVG(epa.epa_avg) - AVG(oaq.oaq_avg) DESC
LIMIT 3