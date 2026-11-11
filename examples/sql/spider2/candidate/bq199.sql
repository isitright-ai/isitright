WITH per_txn AS (
  SELECT
    category_name,
    EXTRACT(YEAR FROM date) AS yr,
    SAFE_DIVIDE(state_bottle_retail, bottle_volume_ml / 1000.0) AS price_per_liter
  FROM `bigquery-public-data.iowa_liquor_sales.sales`
  WHERE date BETWEEN DATE '2019-01-01' AND DATE '2021-12-31'
    AND category_name IS NOT NULL
),
top_cats AS (
  SELECT category_name, AVG(price_per_liter) AS avg_2021
  FROM per_txn
  WHERE yr = 2021
  GROUP BY category_name
  ORDER BY avg_2021 DESC
  LIMIT 10
)
SELECT
  t.category_name,
  AVG(IF(p.yr = 2019, p.price_per_liter, NULL)) AS avg_price_per_liter_2019,
  AVG(IF(p.yr = 2020, p.price_per_liter, NULL)) AS avg_price_per_liter_2020,
  AVG(IF(p.yr = 2021, p.price_per_liter, NULL)) AS avg_price_per_liter_2021
FROM top_cats t
JOIN per_txn p USING (category_name)
GROUP BY t.category_name
ORDER BY avg_price_per_liter_2021 DESC