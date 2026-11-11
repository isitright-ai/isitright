WITH s AS (
  SELECT
    fullVisitorId,
    visitStartTime,
    device.isMobile AS isMobile,
    EXISTS(SELECT 1 FROM UNNEST(hits) h WHERE h.transaction.transactionId IS NOT NULL) AS has_tx
  FROM `bigquery-public-data.google_analytics_sample.ga_sessions_*`
  WHERE _TABLE_SUFFIX BETWEEN '20160801' AND '20170801'
),
u AS (
  SELECT
    fullVisitorId,
    MIN(visitStartTime) AS first_visit,
    ARRAY_AGG(IF(has_tx, STRUCT(visitStartTime AS t, isMobile AS m), NULL) IGNORE NULLS ORDER BY visitStartTime LIMIT 1)[SAFE_OFFSET(0)] AS tx_event,
    ARRAY_AGG(STRUCT(visitStartTime AS t, isMobile AS m) ORDER BY visitStartTime DESC LIMIT 1)[OFFSET(0)] AS last_event
  FROM s
  GROUP BY fullVisitorId
),
e AS (
  SELECT
    fullVisitorId,
    first_visit,
    COALESCE(tx_event, last_event) AS ev
  FROM u
)
SELECT
  MAX(TIMESTAMP_DIFF(TIMESTAMP_SECONDS(ev.t), TIMESTAMP_SECONDS(first_visit), DAY)) AS longest_days
FROM e
WHERE ev.m = TRUE