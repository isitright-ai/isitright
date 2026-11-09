WITH monthly AS (
  SELECT
    EXTRACT(MONTH FROM end_date) AS m,
    SUM(IF(subscriber_type = 'Customer', duration_sec, 0)) / 60 / 1000 AS cust_k_min,
    SUM(IF(subscriber_type = 'Subscriber', duration_sec, 0)) / 60 / 1000 AS sub_k_min
  FROM `bigquery-public-data.san_francisco_bikeshare.bikeshare_trips`
  WHERE EXTRACT(YEAR FROM end_date) = 2017
  GROUP BY m
),
cum AS (
  SELECT
    m,
    SUM(cust_k_min) OVER (ORDER BY m) AS cum_cust,
    SUM(sub_k_min) OVER (ORDER BY m) AS cum_sub
  FROM monthly
)
SELECT m AS month
FROM cum
ORDER BY ABS(cum_cust - cum_sub) DESC
LIMIT 1