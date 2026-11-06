WITH outcomes AS (
  SELECT
    season,
    'win' AS label,
    win_seed AS seed,
    win_school_ncaa AS school_ncaa,
    lose_seed AS opponent_seed,
    lose_school_ncaa AS opponent_school_ncaa
  FROM `data-to-insights.ncaa.mbb_historical_tournament_games`
  WHERE season >= 2014
  UNION ALL
  SELECT
    season,
    'loss' AS label,
    lose_seed AS seed,
    lose_school_ncaa AS school_ncaa,
    win_seed AS opponent_seed,
    win_school_ncaa AS opponent_school_ncaa
  FROM `data-to-insights.ncaa.mbb_historical_tournament_games`
  WHERE season >= 2014
  UNION ALL
  SELECT
    season,
    label,
    seed,
    school_ncaa,
    opponent_seed,
    opponent_school_ncaa
  FROM `data-to-insights.ncaa.2018_tournament_results`
)
SELECT
  o.season,
  o.label,
  o.seed,
  o.school_ncaa,
  team.pace_rank,
  team.poss_40min,
  team.pace_rating,
  team.efficiency_rank,
  team.pts_100poss,
  team.efficiency_rating,
  o.opponent_seed,
  o.opponent_school_ncaa,
  opp.pace_rank AS opp_pace_rank,
  opp.poss_40min AS opp_poss_40min,
  opp.pace_rating AS opp_pace_rating,
  opp.efficiency_rank AS opp_efficiency_rank,
  opp.pts_100poss AS opp_pts_100poss,
  opp.efficiency_rating AS opp_efficiency_rating,
  opp.pace_rank - team.pace_rank AS pace_rank_diff,
  opp.poss_40min - team.poss_40min AS pace_stat_diff,
  opp.pace_rating - team.pace_rating AS pace_rating_diff,
  opp.efficiency_rank - team.efficiency_rank AS eff_rank_diff,
  opp.pts_100poss - team.pts_100poss AS eff_stat_diff,
  opp.efficiency_rating - team.efficiency_rating AS eff_rating_diff
FROM outcomes AS o
LEFT JOIN `data-to-insights.ncaa.feature_engineering` AS team
  ON o.school_ncaa = team.team AND o.season = team.season
LEFT JOIN `data-to-insights.ncaa.feature_engineering` AS opp
  ON o.opponent_school_ncaa = opp.team AND o.season = opp.season