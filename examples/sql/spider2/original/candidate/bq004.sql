WITH purchases AS (
  SELECT
    s.fullVisitorId,
    p.v2ProductName AS product_name,
    p.productQuantity AS qty
  FROM `bigquery-public-data.google_analytics_sample.ga_sessions_*` s,
    UNNEST(s.hits) h,
    UNNEST(h.product) p
  WHERE _TABLE_SUFFIX BETWEEN '20170701' AND '20170731'
    AND p.productRevenue IS NOT NULL
),
youtube_buyers AS (
  SELECT DISTINCT fullVisitorId
  FROM purchases
  WHERE product_name LIKE '%YouTube%'
)
SELECT
  product_name,
  SUM(qty) AS total_quantity
FROM purchases
WHERE fullVisitorId IN (SELECT fullVisitorId FROM youtube_buyers)
  AND product_name NOT LIKE '%YouTube%'
GROUP BY product_name
ORDER BY total_quantity DESC
LIMIT 1