WITH daily AS (
  SELECT date, COUNT(*) AS cnt
  FROM `bigquery-public-data.austin_incidents.incidents_*`
  WHERE _TABLE_SUFFIX = '2016'
    AND descript = 'PUBLIC INTOXICATION'
    AND EXTRACT(YEAR FROM date) = 2016
  GROUP BY date
),
scored AS (
  SELECT date, SAFE_DIVIDE(cnt - AVG(cnt) OVER (), STDDEV(cnt) OVER ()) AS z
  FROM daily
),
ranked AS (
  SELECT date, z, DENSE_RANK() OVER (ORDER BY z DESC) AS rnk
  FROM scored
)
SELECT FORMAT_DATE('%Y-%m-%d', date) AS date
FROM ranked
WHERE rnk = 2