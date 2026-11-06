WITH s AS (
  SELECT
    SUBSTR(CoC_Number, 1, 2) AS state,
    SUM(IF(Count_Year = 2015, Unsheltered_Homeless, 0)) AS u2015,
    SUM(IF(Count_Year = 2018, Unsheltered_Homeless, 0)) AS u2018
  FROM `bigquery-public-data.sdoh_hud_pit_homelessness.hud_pit_by_coc`
  WHERE Count_Year IN (2015, 2018)
  GROUP BY state
),
p AS (
  SELECT state, SAFE_DIVIDE(u2018 - u2015, u2015) * 100 AS pct_change
  FROM s
),
v AS (
  SELECT state, pct_change
  FROM p
  WHERE pct_change IS NOT NULL
)
SELECT state
FROM v
ORDER BY ABS(pct_change - (SELECT AVG(pct_change) FROM v))
LIMIT 5