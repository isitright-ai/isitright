SELECT
  SAFE_DIVIDE(COUNT(DISTINCT IF(totals.transactions IS NOT NULL, fullVisitorId, NULL)), COUNT(DISTINCT fullVisitorId)) AS conversion_rate,
  SAFE_DIVIDE(SUM(IF(totals.transactions IS NOT NULL, totals.transactions, 0)), COUNT(DISTINCT IF(totals.transactions IS NOT NULL, fullVisitorId, NULL))) AS avg_transactions_per_purchaser
FROM `data-to-insights.ecommerce.web_analytics`