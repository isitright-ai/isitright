WITH purchases AS (
  SELECT
    SUBSTR(event_date, 1, 6) AS month,
    user_pseudo_id,
    i.item_name,
    i.quantity
  FROM `bigquery-public-data.ga4_obfuscated_sample_ecommerce.events_*`, UNNEST(items) AS i
  WHERE _TABLE_SUFFIX BETWEEN '20201101' AND '20210131'
    AND event_name = 'purchase'
),
buyers AS (
  SELECT DISTINCT month, user_pseudo_id
  FROM purchases
  WHERE item_name = 'Google Red Speckled Tee'
),
other AS (
  SELECT p.month, p.item_name, SUM(p.quantity) AS quantity
  FROM purchases p
  JOIN buyers b
    ON p.month = b.month AND p.user_pseudo_id = b.user_pseudo_id
  WHERE p.item_name != 'Google Red Speckled Tee'
  GROUP BY p.month, p.item_name
),
ranked AS (
  SELECT
    month,
    item_name,
    quantity,
    RANK() OVER (PARTITION BY month ORDER BY quantity DESC) AS rnk
  FROM other
)
SELECT month, item_name, quantity
FROM ranked
WHERE rnk = 1
ORDER BY month