SELECT COUNT(*) AS user_count
FROM (
  SELECT
    user_pseudo_id,
    MAX(IF(event_date >= '20210106', 1, 0)) AS active_last_2_days
  FROM (SELECT t.* EXCEPT (_shard), SUBSTR(CONCAT('events_', t._shard), 8) AS _TABLE_SUFFIX FROM `bigquery-public-data.ga4_obfuscated_sample_ecommerce.events` AS t WHERE SUBSTR(CONCAT('events_', t._shard), 1, 7) = 'events_'),
    UNNEST(event_params) AS ep
  WHERE _TABLE_SUFFIX BETWEEN '20210101' AND '20210107'
    AND ep.key = 'engagement_time_msec'
    AND ep.value.int_value > 0
    AND user_pseudo_id IS NOT NULL
  GROUP BY user_pseudo_id
)
WHERE active_last_2_days = 0