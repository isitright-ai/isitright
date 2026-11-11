WITH purchasers AS (
  SELECT DISTINCT user_pseudo_id
  FROM `bigquery-public-data.ga4_obfuscated_sample_ecommerce.events_*`
  WHERE _TABLE_SUFFIX BETWEEN '20201101' AND '20201130'
    AND event_name = 'purchase'
    AND user_pseudo_id IS NOT NULL
),
daily AS (
  SELECT
    e.event_date,
    e.user_pseudo_id,
    COUNT(*) AS page_views
  FROM `bigquery-public-data.ga4_obfuscated_sample_ecommerce.events_*` e
  JOIN purchasers p ON e.user_pseudo_id = p.user_pseudo_id
  WHERE e._TABLE_SUFFIX BETWEEN '20201101' AND '20201130'
    AND e.event_name = 'page_view'
  GROUP BY e.event_date, e.user_pseudo_id
)
SELECT
  event_date,
  SUM(page_views) AS total_page_views,
  SAFE_DIVIDE(SUM(page_views), COUNT(DISTINCT user_pseudo_id)) AS avg_page_views_per_user
FROM daily
GROUP BY event_date
ORDER BY event_date