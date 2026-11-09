WITH purchases AS (
  SELECT
    e.ecommerce.transaction_id AS transaction_id,
    e.ecommerce.total_item_quantity AS total_item_quantity,
    e.ecommerce.purchase_revenue_in_usd AS purchase_revenue_in_usd,
    e.ecommerce.purchase_revenue AS purchase_revenue,
    i.item_category AS item_category,
    SAFE_DIVIDE(e.ecommerce.tax_value_in_usd, e.ecommerce.purchase_revenue_in_usd) AS tax_rate
  FROM `bigquery-public-data.ga4_obfuscated_sample_ecommerce.events_*` AS e, UNNEST(e.items) AS i
  WHERE e._TABLE_SUFFIX = '20201130'
    AND e.event_name = 'purchase'
),
top_category AS (
  SELECT item_category
  FROM purchases
  WHERE tax_rate IS NOT NULL
  ORDER BY tax_rate DESC
  LIMIT 1
)
SELECT DISTINCT
  p.transaction_id,
  p.total_item_quantity,
  p.purchase_revenue_in_usd,
  p.purchase_revenue
FROM purchases AS p
JOIN top_category AS t
  ON p.item_category = t.item_category