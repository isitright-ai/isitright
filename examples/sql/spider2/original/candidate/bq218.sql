WITH yearly AS (
  SELECT
    item_number,
    ANY_VALUE(item_description) AS item_description,
    SUM(IF(EXTRACT(YEAR FROM date) = 2023, sale_dollars, 0)) AS sales_2023,
    SUM(IF(EXTRACT(YEAR FROM date) = 2022, sale_dollars, 0)) AS sales_2022
  FROM `bigquery-public-data.iowa_liquor_sales.sales`
  WHERE date >= DATE '2022-01-01' AND date < DATE '2024-01-01'
  GROUP BY item_number
)
SELECT
  item_number,
  item_description,
  sales_2022,
  sales_2023,
  SAFE_DIVIDE(sales_2023 - sales_2022, sales_2022) * 100 AS yoy_growth_percentage
FROM yearly
WHERE sales_2022 > 0
ORDER BY yoy_growth_percentage DESC
LIMIT 5