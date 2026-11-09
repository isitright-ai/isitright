SELECT zip_code
FROM `bigquery-public-data.fdic_banks.locations`
WHERE state = 'FL'
GROUP BY zip_code
ORDER BY COUNT(DISTINCT fdic_certificate_number) DESC
LIMIT 1