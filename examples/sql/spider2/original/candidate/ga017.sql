WITH pv AS (
  SELECT
    user_pseudo_id,
    (SELECT ep.value.string_value FROM UNNEST(event_params) ep WHERE ep.key = 'page_location') AS page
  FROM `bigquery-public-data.ga4_obfuscated_sample_ecommerce.events_*`
  WHERE _TABLE_SUFFIX BETWEEN '20210101' AND '20210131'
    AND event_name = 'page_view'
),
top_page AS (
  SELECT page
  FROM pv
  WHERE page IS NOT NULL
  GROUP BY page
  ORDER BY COUNT(*) DESC
  LIMIT 1
)
SELECT COUNT(DISTINCT user_pseudo_id) AS distinct_users
FROM pv
WHERE page = (SELECT page FROM top_page)