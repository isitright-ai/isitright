WITH top_drug AS (
  SELECT drug_name
  FROM `bigquery-public-data.cms_medicare.part_d_prescriber_2014`
  WHERE nppes_provider_state = 'NY'
  GROUP BY drug_name
  ORDER BY SUM(total_claim_count) DESC
  LIMIT 1
)
SELECT
  p.nppes_provider_state AS state,
  SUM(p.total_claim_count) AS total_claim_count,
  SUM(p.total_drug_cost) AS total_drug_cost
FROM `bigquery-public-data.cms_medicare.part_d_prescriber_2014` p
JOIN top_drug t ON p.drug_name = t.drug_name
GROUP BY p.nppes_provider_state
ORDER BY total_claim_count DESC
LIMIT 5