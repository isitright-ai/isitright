WITH b AS (
  SELECT
    SPLIT(zip_code, '.')[OFFSET(0)] AS zip,
    DATE_TRUNC(date, MONTH) AS month,
    sale_dollars
  FROM `bigquery-public-data.iowa_liquor_sales.sales`
  WHERE UPPER(county) = 'DUBUQUE'
    AND UPPER(category_name) LIKE '%BOURBON%'
    AND date BETWEEN '2022-01-01' AND '2022-12-31'
),
top3 AS (
  SELECT zip
  FROM b
  GROUP BY zip
  ORDER BY SUM(sale_dollars) DESC
  LIMIT 1 OFFSET 2
),
pop AS (
  SELECT zipcode, SUM(population) AS pop21
  FROM `bigquery-public-data.census_bureau_usa.population_by_zip_2010`
  WHERE minimum_age >= 21
    AND gender IN ('male', 'female')
  GROUP BY zipcode
)
SELECT
  b.month,
  SAFE_DIVIDE(SUM(b.sale_dollars), MAX(pop.pop21)) AS per_capita_sales
FROM b
JOIN top3 ON b.zip = top3.zip
JOIN pop ON pop.zipcode = b.zip
GROUP BY b.month
ORDER BY b.month