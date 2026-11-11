WITH installs AS (
  SELECT user_pseudo_id, MIN(event_timestamp) AS ts
  FROM `firebase-public-project.analytics_153293282.events_*`
  WHERE event_name = 'first_open'
    AND _TABLE_SUFFIX BETWEEN '20180801' AND '20180930'
  GROUP BY user_pseudo_id
),
removes AS (
  SELECT user_pseudo_id, event_timestamp
  FROM `firebase-public-project.analytics_153293282.events_*`
  WHERE event_name = 'app_remove'
    AND _TABLE_SUFFIX BETWEEN '20180801' AND '20181003'
),
flags AS (
  SELECT i.user_pseudo_id,
    COUNTIF(r.event_timestamp BETWEEN i.ts AND i.ts + 7 * 24 * 3600 * 1000000) > 0 AS uninstalled_7d
  FROM installs i
  LEFT JOIN removes r ON r.user_pseudo_id = i.user_pseudo_id
  GROUP BY i.user_pseudo_id
)
SELECT 100 * SAFE_DIVIDE(COUNTIF(NOT uninstalled_7d), COUNT(*)) AS percentage
FROM flags