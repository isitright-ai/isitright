WITH s AS (
  SELECT
    SUBSTR(date, 1, 6) AS month,
    fullVisitorId,
    totals.pageviews AS pageviews,
    totals.transactions AS transactions,
    COALESCE((SELECT LOGICAL_OR(p.productRevenue IS NOT NULL) FROM UNNEST(hits) h, UNNEST(h.product) p), FALSE) AS has_rev
  FROM `bigquery-public-data.google_analytics_sample.ga_sessions_*`
  WHERE _TABLE_SUFFIX BETWEEN '20170401' AND '20170731'
)
SELECT
  month,
  SAFE_DIVIDE(SUM(IF(transactions >= 1 AND has_rev, pageviews, NULL)), COUNT(DISTINCT IF(transactions >= 1 AND has_rev, fullVisitorId, NULL))) AS avg_pageviews_per_visitor_purchase,
  SAFE_DIVIDE(SUM(IF(transactions IS NULL AND NOT has_rev, pageviews, NULL)), COUNT(DISTINCT IF(transactions IS NULL AND NOT has_rev, fullVisitorId, NULL))) AS avg_pageviews_per_visitor_non_purchase
FROM s
GROUP BY month
ORDER BY month