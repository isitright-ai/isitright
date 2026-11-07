WITH s AS (
  SELECT
    SUBSTR(date, 1, 6) AS month,
    fullVisitorId,
    IF(IFNULL(totals.transactions, 0) >= 1, 'purchase', 'non_purchase') AS cls,
    totals.pageviews AS pageviews
  FROM `bigquery-public-data.google_analytics_sample.ga_sessions_*`
  WHERE _TABLE_SUFFIX BETWEEN '20170601' AND '20170731'
    AND totals.pageviews IS NOT NULL
),
v AS (
  SELECT month, cls, fullVisitorId, SUM(pageviews) AS total_pv
  FROM s
  GROUP BY month, cls, fullVisitorId
)
SELECT
  month,
  SAFE_DIVIDE(SUM(IF(cls = 'purchase', total_pv, 0)), COUNT(DISTINCT IF(cls = 'purchase', fullVisitorId, NULL))) AS avg_pageviews_purchase,
  SAFE_DIVIDE(SUM(IF(cls = 'non_purchase', total_pv, 0)), COUNT(DISTINCT IF(cls = 'non_purchase', fullVisitorId, NULL))) AS avg_pageviews_non_purchase
FROM v
GROUP BY month
ORDER BY month