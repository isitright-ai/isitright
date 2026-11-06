CREATE TABLE `data-to-insights.ncaa.2018_tournament_results`
(
  season INT64,
  round INT64,
  days_from_epoch INT64,
  game_date DATE,
  day STRING,
  label STRING,
  seed STRING,
  market STRING,
  name STRING,
  alias STRING,
  school_ncaa STRING,
  points INT64,
  opponent_seed STRING,
  opponent_market STRING,
  opponent_name STRING,
  opponent_alias STRING,
  opponent_school_ncaa STRING,
  opponent_points INT64
);

CREATE TABLE `data-to-insights.ncaa.feature_engineering`
(
  season INT64,
  team STRING,
  poss_40min FLOAT64,
  pace_rating FLOAT64,
  pace_rank FLOAT64,
  pts_100poss FLOAT64,
  efficiency_rating FLOAT64,
  efficiency_rank FLOAT64
);

CREATE TABLE `data-to-insights.ncaa.mbb_historical_tournament_games`
(
  season INT64 OPTIONS(description="Year the game was played in. Note that this is different from the \"season\" values in other tables here, which use academic year."),
  round INT64 OPTIONS(description="Tournament round, indicated by the number of teams playing in that round"),
  days_from_epoch INT64 OPTIONS(description="Days from epoch, as defined in the Kaggle competition (https://www.kaggle.com/c/mens-machine-learning-competition-2018/data)"),
  game_date DATE OPTIONS(description="Date the game was played"),
  day STRING OPTIONS(description="Day of the week the game was played"),
  win_seed STRING OPTIONS(description="Seed of the winning team"),
  win_region STRING OPTIONS(description="Region of the winning team, as defined in the Kaggle competition (https://www.kaggle.com/c/mens-machine-learning-competition-2018/data)"),
  win_market STRING OPTIONS(description="School name (using Sportradar names) of the winning team"),
  win_name STRING OPTIONS(description="Team name of the winning team"),
  win_alias STRING OPTIONS(description="Team alias of the winning team"),
  win_team_id STRING OPTIONS(description="Sportradar team ID of the winning team"),
  win_school_ncaa STRING OPTIONS(description="School name of the winning team (see http://stats.ncaa.org/game_upload/team_codes)"),
  win_code_ncaa INT64 OPTIONS(description="School code of the winning team (see http://stats.ncaa.org/game_upload/team_codes)"),
  win_kaggle_team_id INT64 OPTIONS(description="Kaggle team ID of the winning team"),
  win_pts INT64 OPTIONS(description="Points scored by the winning team"),
  lose_seed STRING OPTIONS(description="Seed of the losing team"),
  lose_region STRING OPTIONS(description="Region of the losing team, as defined in the Kaggle competition (https://www.kaggle.com/c/mens-machine-learning-competition-2018/data)"),
  lose_market STRING OPTIONS(description="School name (using Sportradar names) of the losing team"),
  lose_name STRING OPTIONS(description="Team name of the losing team"),
  lose_alias STRING OPTIONS(description="Team alias of the losing team"),
  lose_team_id STRING OPTIONS(description="Sportradar team ID of the losing team"),
  lose_school_ncaa STRING OPTIONS(description="School name of the losing team (see http://stats.ncaa.org/game_upload/team_codes)"),
  lose_code_ncaa INT64 OPTIONS(description="School code of the losing team (see http://stats.ncaa.org/game_upload/team_codes)"),
  lose_kaggle_team_id INT64 OPTIONS(description="Kaggle team ID of the losing team"),
  lose_pts INT64 OPTIONS(description="Points scored by the losing team"),
  num_ot INT64 OPTIONS(description="Number of overtime periods played in the game"),
  academic_year INT64 OPTIONS(description="The academic year the game was played in")
)
OPTIONS(
  description="Game score information from Men's Basketball games, starting with the 1984-85 tournament. Each row shows one game."
);
