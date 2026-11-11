WITH s AS (
  SELECT
    season,
    market,
    wins,
    MAX(wins) OVER (PARTITION BY season) AS max_wins
  FROM `bigquery-public-data.ncaa_basketball.mbb_historical_teams_seasons`
  WHERE season BETWEEN 1900 AND 2000
    AND market IS NOT NULL
)
SELECT
  market,
  COUNT(*) AS peak_seasons
FROM s
WHERE wins = max_wins
GROUP BY market
ORDER BY peak_seasons DESC, market
LIMIT 5