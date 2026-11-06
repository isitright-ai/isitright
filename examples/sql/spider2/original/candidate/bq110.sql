WITH y AS (
  SELECT
    CoC_Number,
    CoC_Name,
    SUM(IF(Count_Year = 2012, Homeless_Veterans, NULL)) AS vets_2012,
    SUM(IF(Count_Year = 2018, Homeless_Veterans, NULL)) AS vets_2018
  FROM `bigquery-public-data.sdoh_hud_pit_homelessness.hud_pit_by_coc`
  WHERE CoC_Number LIKE 'NY-%'
    AND Count_Year IN (2012, 2018)
  GROUP BY CoC_Number, CoC_Name
)
SELECT
  CoC_Number,
  CoC_Name,
  vets_2012,
  vets_2018,
  vets_2018 - vets_2012 AS change_in_homeless_veterans
FROM y
WHERE vets_2012 IS NOT NULL
  AND vets_2018 IS NOT NULL
ORDER BY CoC_Number