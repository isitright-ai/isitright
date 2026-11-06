WITH s AS (
  SELECT
    user_pseudo_id,
    (SELECT ep.value.int_value FROM UNNEST(event_params) ep WHERE ep.key = 'ga_session_id') AS session_id,
    ARRAY_AGG(STRUCT(LOWER(IFNULL(traffic_source.source, '')) AS source, LOWER(IFNULL(traffic_source.medium, '')) AS medium, LOWER(IFNULL(traffic_source.name, '')) AS campaign) ORDER BY event_timestamp LIMIT 1)[OFFSET(0)] AS ts
  FROM `bigquery-public-data.ga4_obfuscated_sample_ecommerce.events_*`
  WHERE _TABLE_SUFFIX BETWEEN '20201201' AND '20201231'
  GROUP BY user_pseudo_id, session_id
  HAVING session_id IS NOT NULL
),
c AS (
  SELECT
    CASE
      WHEN ts.source = '(direct)' AND ts.medium IN ('(not set)', '(none)', '') THEN 'Direct'
      WHEN REGEXP_CONTAINS(ts.campaign, r'cross-network') THEN 'Cross-network'
      WHEN (REGEXP_CONTAINS(ts.source, r'alibaba|amazon|google shopping|shopify|etsy|ebay|stripe|walmart') OR REGEXP_CONTAINS(ts.campaign, r'^(.*(([^a-df-z]|^)shop|shopping).*)$'))
           AND REGEXP_CONTAINS(ts.medium, r'^(.*cp.*|ppc|retargeting|paid.*)$') THEN 'Paid Shopping'
      WHEN REGEXP_CONTAINS(ts.source, r'baidu|bing|duckduckgo|ecosia|google|yahoo|yandex')
           AND REGEXP_CONTAINS(ts.medium, r'^(.*cp.*|ppc|paid.*)$') THEN 'Paid Search'
      WHEN REGEXP_CONTAINS(ts.source, r'badoo|facebook|fb|instagram|linkedin|pinterest|tiktok|twitter|whatsapp')
           AND REGEXP_CONTAINS(ts.medium, r'^(.*cp.*|ppc|retargeting|paid.*)$') THEN 'Paid Social'
      WHEN REGEXP_CONTAINS(ts.source, r'dailymotion|disneyplus|netflix|youtube|vimeo|twitch')
           AND REGEXP_CONTAINS(ts.medium, r'^(.*cp.*|ppc|retargeting|paid.*)$') THEN 'Paid Video'
      WHEN ts.medium IN ('display', 'banner', 'expandable', 'interstitial', 'cpm') THEN 'Display'
      WHEN REGEXP_CONTAINS(ts.source, r'alibaba|amazon|google shopping|shopify|etsy|ebay|stripe|walmart')
           OR REGEXP_CONTAINS(ts.campaign, r'^(.*(([^a-df-z]|^)shop|shopping).*)$') THEN 'Organic Shopping'
      WHEN REGEXP_CONTAINS(ts.source, r'badoo|facebook|fb|instagram|linkedin|pinterest|tiktok|twitter|whatsapp')
           OR ts.medium IN ('social', 'social-network', 'social-media', 'sm', 'social network', 'social media') THEN 'Organic Social'
      WHEN REGEXP_CONTAINS(ts.source, r'dailymotion|disneyplus|netflix|youtube|vimeo|twitch')
           OR REGEXP_CONTAINS(ts.medium, r'video') THEN 'Organic Video'
      WHEN REGEXP_CONTAINS(ts.source, r'baidu|bing|duckduckgo|ecosia|google|yahoo|yandex')
           OR ts.medium = 'organic' THEN 'Organic Search'
      WHEN ts.medium = 'referral' THEN 'Referral'
      WHEN REGEXP_CONTAINS(ts.source, r'^(email|e-mail|e_mail|e mail)$')
           OR REGEXP_CONTAINS(ts.medium, r'^(email|e-mail|e_mail|e mail)$') THEN 'Email'
      WHEN ts.medium = 'affiliate' THEN 'Affiliates'
      WHEN ts.medium = 'audio' THEN 'Audio'
      WHEN ts.source = 'sms' OR ts.medium = 'sms' THEN 'SMS'
      WHEN ts.medium LIKE '%push' OR ts.medium LIKE '%mobile%' OR ts.medium LIKE '%notification%' THEN 'Mobile Push Notifications'
      ELSE 'Unassigned'
    END AS channel
  FROM s
)
SELECT channel, COUNT(*) AS sessions
FROM c
GROUP BY channel
ORDER BY sessions DESC
LIMIT 1 OFFSET 3