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

CREATE TABLE `bigquery-public-data.stackoverflow.users`
(
  id INT64,
  display_name STRING,
  about_me STRING,
  age STRING,
  creation_date TIMESTAMP,
  last_access_date TIMESTAMP,
  location STRING,
  reputation INT64,
  up_votes INT64,
  down_votes INT64,
  views INT64,
  profile_image_url STRING,
  website_url STRING
);
