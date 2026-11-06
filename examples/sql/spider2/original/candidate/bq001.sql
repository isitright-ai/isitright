WITH s AS (
  SELECT
    fullVisitorId,
    PARSE_DATE('%Y%m%d', date) AS d,
    visitStartTime,
    device.deviceCategory AS dc,
    (SELECT COUNT(1) FROM UNNEST(hits) h WHERE h.transaction.transactionId IS NOT NULL) AS tx
  FROM `bigquery-public-data.google_analytics_sample.ga_sessions_*`
  WHERE _TABLE_SUFFIX BETWEEN '20170201' AND '20170228'
),
first_visit AS (
  SELECT fullVisitorId, MIN(d) AS first_visit_date
  FROM s
  GROUP BY fullVisitorId
),
first_tx AS (
  SELECT
    fullVisitorId,
    d AS first_tx_date,
    dc AS device_category,
    ROW_NUMBER() OVER (PARTITION BY fullVisitorId ORDER BY visitStartTime) AS rn
  FROM s
  WHERE tx > 0
)
SELECT
  t.fullVisitorId,
  DATE_DIFF(t.first_tx_date, v.first_visit_date, DAY) AS days_elapsed,
  t.device_category
FROM first_tx t
JOIN first_visit v ON t.fullVisitorId = v.fullVisitorId
WHERE t.rn = 1