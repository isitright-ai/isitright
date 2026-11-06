WITH f AS (
  SELECT
    name,
    SUM(IF(state = 'WY', number, 0)) AS wy_number,
    SUM(number) AS total_number
  FROM `bigquery-public-data.usa_names.usa_1910_current`
  WHERE gender = 'F' AND year = 2021
  GROUP BY name
)
SELECT name
FROM f
WHERE wy_number > 0
ORDER BY SAFE_DIVIDE(wy_number, total_number) DESC, wy_number DESC
LIMIT 1