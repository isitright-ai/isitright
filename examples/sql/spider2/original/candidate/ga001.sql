WITH purchases AS (
  SELECT
    e.user_pseudo_id,
    i.item_name,
    i.quantity
  FROM `bigquery-public-data.ga4_obfuscated_sample_ecommerce.events_*` AS e,
    UNNEST(e.items) AS i
  WHERE _TABLE_SUFFIX BETWEEN '20201201' AND '20201231'
    AND e.event_name = 'purchase'
),
buyers AS (
  SELECT DISTINCT user_pseudo_id
  FROM purchases
  WHERE item_name = 'Google Navy Speckled Tee'
)
SELECT
  item_name,
  SUM(quantity) AS total_quantity
FROM purchases
WHERE user_pseudo_id IN (SELECT user_pseudo_id FROM buyers)
  AND item_name != 'Google Navy Speckled Tee'
GROUP BY item_name
ORDER BY total_quantity DESC
LIMIT 1