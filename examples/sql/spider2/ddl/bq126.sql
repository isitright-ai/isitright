CREATE TABLE `bigquery-public-data.the_met.images`
(
  object_id INT64,
  public_caption STRING,
  title STRING,
  original_image_url STRING,
  caption STRING,
  is_oasc BOOL,
  gcs_url STRING
);

CREATE TABLE `bigquery-public-data.the_met.objects`
(
  object_number STRING,
  is_highlight BOOL,
  is_public_domain BOOL,
  object_id INT64,
  department STRING,
  object_name STRING,
  title STRING,
  culture STRING,
  period STRING,
  dynasty STRING,
  reign STRING,
  portfolio STRING,
  artist_role STRING,
  artist_prefix STRING,
  artist_display_name STRING,
  artist_display_bio STRING,
  artist_suffix STRING,
  artist_alpha_sort STRING,
  artist_nationality STRING,
  artist_begin_date STRING,
  artist_end_date STRING,
  object_date STRING,
  object_begin_date INT64,
  object_end_date INT64,
  medium STRING,
  dimensions STRING,
  credit_line STRING,
  geography_type STRING,
  city STRING,
  state STRING,
  county STRING,
  country STRING,
  region STRING,
  subregion STRING,
  locale STRING,
  locus STRING,
  excavation STRING,
  river STRING,
  classification STRING,
  rights_and_reproduction STRING,
  link_resource STRING,
  metadata_date TIMESTAMP,
  repository STRING
);
