CREATE TABLE `bigquery-public-data.stackoverflow.comments`
(
  id INT64,
  text STRING,
  creation_date TIMESTAMP,
  post_id INT64,
  user_id INT64,
  user_display_name STRING,
  score INT64
);

CREATE TABLE `bigquery-public-data.stackoverflow.posts_answers`
(
  id INT64,
  title STRING,
  body STRING,
  accepted_answer_id STRING,
  answer_count STRING,
  comment_count INT64,
  community_owned_date TIMESTAMP,
  creation_date TIMESTAMP,
  favorite_count STRING,
  last_activity_date TIMESTAMP,
  last_edit_date TIMESTAMP,
  last_editor_display_name STRING,
  last_editor_user_id INT64,
  owner_display_name STRING,
  owner_user_id INT64,
  parent_id INT64,
  post_type_id INT64,
  score INT64,
  tags STRING,
  view_count STRING
);

CREATE TABLE `bigquery-public-data.stackoverflow.posts_questions`
(
  id INT64,
  title STRING,
  body STRING,
  accepted_answer_id INT64,
  answer_count INT64,
  comment_count INT64,
  community_owned_date TIMESTAMP,
  creation_date TIMESTAMP,
  favorite_count INT64,
  last_activity_date TIMESTAMP,
  last_edit_date TIMESTAMP,
  last_editor_display_name STRING,
  last_editor_user_id INT64,
  owner_display_name STRING,
  owner_user_id INT64,
  parent_id STRING,
  post_type_id INT64,
  score INT64,
  tags STRING,
  view_count INT64
);
