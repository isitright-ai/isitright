WITH o AS (
  SELECT provider_id, ANY_VALUE(provider_name) AS provider_name, AVG(average_total_payments) AS avg_outpatient_cost
  FROM (SELECT t.* EXCEPT (_shard), SUBSTR(CONCAT('outpatient_charges_', t._shard), 20) AS _TABLE_SUFFIX FROM `bigquery-public-data.cms_medicare.outpatient_charges` AS t WHERE SUBSTR(CONCAT('outpatient_charges_', t._shard), 1, 19) = 'outpatient_charges_')
  WHERE _TABLE_SUFFIX = '2014'
  GROUP BY provider_id
),
i AS (
  SELECT provider_id, AVG(average_total_payments) AS avg_inpatient_cost
  FROM (SELECT t.* EXCEPT (_shard), SUBSTR(CONCAT('inpatient_charges_', t._shard), 19) AS _TABLE_SUFFIX FROM `bigquery-public-data.cms_medicare.inpatient_charges` AS t WHERE SUBSTR(CONCAT('inpatient_charges_', t._shard), 1, 18) = 'inpatient_charges_')
  WHERE _TABLE_SUFFIX = '2014'
  GROUP BY provider_id
)
SELECT o.provider_id, o.provider_name, o.avg_outpatient_cost + i.avg_inpatient_cost AS combined_average_cost
FROM o
JOIN i ON o.provider_id = i.provider_id
ORDER BY combined_average_cost DESC
LIMIT 1