CREATE TABLE `bigquery-public-data.ncaa_basketball.mbb_historical_teams_seasons`
(
  season INT64 OPTIONS(description="Season the game was played in"),
  market STRING OPTIONS(description="Team school name (using Sportradar names)"),
  name STRING OPTIONS(description="Team name"),
  team_code INT64 OPTIONS(description="School code (see http://stats.ncaa.org/game_upload/team_codes)"),
  team_id STRING OPTIONS(description="Sportradar team ID"),
  alias STRING OPTIONS(description="Team alias"),
  division INT64 OPTIONS(description="The division the team played in at this time of this season"),
  current_division STRING OPTIONS(description="The division the team currently plays in"),
  wins INT64 OPTIONS(description="Number of wins in this season"),
  losses INT64 OPTIONS(description="Number of losses in this season"),
  ties INT64 OPTIONS(description="Number of ties in this season")
)
OPTIONS(
  description="Season record information for Men's Basketball, starting with the 1894-95 season. Each game is included twice, with one entry per team. \n\nData provided by the NCAA."
);
