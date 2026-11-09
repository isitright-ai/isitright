WITH purchases AS (
  SELECT
    s.fullVisitorId,
    p.v2ProductName AS product_name,
    p.productQuantity AS qty
  FROM (SELECT t.* EXCEPT (_shard), SUBSTR(CONCAT('ga_sessions_', t._shard), 13) AS _TABLE_SUFFIX FROM `bigquery-public-data.google_analytics_sample.ga_sessions` AS t WHERE SUBSTR(CONCAT('ga_sessions_', t._shard), 1, 12) = 'ga_sessions_') s,
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