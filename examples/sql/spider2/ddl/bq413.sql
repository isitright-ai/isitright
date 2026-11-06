CREATE TABLE `bigquery-public-data.dimensions_ai_covid19.grid`
(
  id STRING,
  status STRING,
  redirect STRING,
  name STRING,
  established INT64,
  closed INT64,
  aliases ARRAY<STRING>,
  acronyms ARRAY<STRING>,
  types ARRAY<STRING>,
  email_address STRING,
  links ARRAY<STRING>,
  wikipedia_url STRING,
  labels ARRAY<STRUCT<label STRING, iso639 STRING>>,
  relationships ARRAY<STRUCT<type STRING, label STRING, id STRING>>,
  external_ids STRUCT<isni STRUCT<preferred STRING, `all` ARRAY<STRING>>, fundref STRUCT<preferred STRING, `all` ARRAY<STRING>>, orgref STRUCT<preferred STRING, `all` ARRAY<STRING>>, wikidata STRUCT<preferred STRING, `all` ARRAY<STRING>>, ror STRUCT<preferred STRING, `all` ARRAY<STRING>>, hesa STRUCT<preferred STRING, `all` ARRAY<STRING>>, ucas STRUCT<preferred STRING, `all` ARRAY<STRING>>, ukprn STRUCT<preferred STRING, `all` ARRAY<STRING>>, cnrs STRUCT<preferred STRING, `all` ARRAY<STRING>>>,
  address STRUCT<line_1 STRING, line_2 STRING, line_3 STRING, latitude FLOAT64, longitude FLOAT64, postcode STRING, city STRING, state STRING, state_code STRING, country STRING, country_code STRING, country_geonames_id INT64, geonames_city STRUCT<id INT64, city STRING, nuts_level1 STRUCT<name STRING, code STRING>, nuts_level2 STRUCT<name STRING, code STRING>, nuts_level3 STRUCT<name STRING, code STRING>, geonames_admin1 STRUCT<name STRING, ascii_name STRING, code STRING>, geonames_admin2 STRUCT<name STRING, ascii_name STRING, code STRING>, license STRUCT<attribution STRING, license STRING>>>
);

CREATE TABLE `bigquery-public-data.dimensions_ai_covid19.publications`
(
  id STRING,
  year INT64,
  doi STRING,
  volume STRING,
  issue STRING,
  pages STRING,
  subtitles ARRAY<STRING>,
  abstract STRUCT<preferred STRING, original STRING>,
  acknowledgements STRUCT<preferred STRING, original STRING>,
  funding_section STRUCT<preferred STRING, original STRING>,
  copyright_statement STRING,
  publisher STRUCT<id STRING, name STRING>,
  pmid STRING,
  pmcid STRING,
  type STRING,
  date STRING,
  date_online STRING,
  date_print STRING,
  open_access_categories ARRAY<STRING>,
  open_access_categories_v2 ARRAY<STRING>,
  book_title STRUCT<preferred STRING, original STRING>,
  book_series_title STRUCT<preferred STRING, original STRING>,
  proceedings_title STRUCT<preferred STRING, original STRING>,
  conference STRUCT<name STRING, location STRING>,
  repository_dois ARRAY<STRING>,
  arxiv_id STRING,
  resulting_publication_doi STRING,
  eisbn STRING,
  isbn STRING,
  editors ARRAY<STRUCT<first_name STRUCT<preferred STRING, original STRING>, last_name STRUCT<preferred STRING, original STRING>>>,
  reference_ids ARRAY<STRING>,
  mesh_headings ARRAY<STRING>,
  mesh_terms ARRAY<STRING>,
  category_bra STRUCT<values ARRAY<STRING>, `full` ARRAY<STRUCT<id STRING, value STRING>>>,
  category_for STRUCT<first_level STRUCT<codes ARRAY<STRING>, `full` ARRAY<STRUCT<id STRING, code STRING, name STRING>>>, second_level STRUCT<codes ARRAY<STRING>, `full` ARRAY<STRUCT<id STRING, code STRING, name STRING>>>>,
  category_hra STRUCT<values ARRAY<STRING>, `full` ARRAY<STRUCT<id STRING, value STRING>>>,
  category_hrcs_hc STRUCT<values ARRAY<STRING>, `full` ARRAY<STRUCT<id STRING, value STRING>>>,
  category_hrcs_rac STRUCT<codes ARRAY<STRING>, `full` ARRAY<STRUCT<id STRING, code STRING, name STRING>>>,
  category_icrp_cso STRUCT<codes ARRAY<STRING>, `full` ARRAY<STRUCT<id STRING, code STRING, name STRING>>>,
  category_icrp_ct STRUCT<values ARRAY<STRING>, `full` ARRAY<STRUCT<id STRING, value STRING>>>,
  category_rcdc STRUCT<values ARRAY<STRING>, `full` ARRAY<STRUCT<id STRING, value STRING>>>,
  category_sdg STRUCT<codes ARRAY<STRING>, `full` ARRAY<STRUCT<id STRING, code STRING, name STRING>>>,
  category_uoa STRUCT<codes ARRAY<STRING>, `full` ARRAY<STRUCT<id STRING, code STRING, name STRING>>>,
  categories STRUCT<bra_v1 STRUCT<values ARRAY<STRING>, `full` ARRAY<STRUCT<id STRING, value STRING>>>, for_v1 STRUCT<first_level STRUCT<codes ARRAY<STRING>, `full` ARRAY<STRUCT<id STRING, code STRING, name STRING>>>, second_level STRUCT<codes ARRAY<STRING>, `full` ARRAY<STRUCT<id STRING, code STRING, name STRING>>>>, hra_v1 STRUCT<values ARRAY<STRING>, `full` ARRAY<STRUCT<id STRING, value STRING>>>, hrcs_hc_v1 STRUCT<values ARRAY<STRING>, `full` ARRAY<STRUCT<id STRING, value STRING>>>, hrcs_rac_v1 STRUCT<codes ARRAY<STRING>, `full` ARRAY<STRUCT<id STRING, code STRING, name STRING>>>, icrp_cso_v1 STRUCT<codes ARRAY<STRING>, `full` ARRAY<STRUCT<id STRING, code STRING, name STRING>>>, icrp_ct_v1 STRUCT<values ARRAY<STRING>, `full` ARRAY<STRUCT<id STRING, value STRING>>>, rcdc_v1 STRUCT<values ARRAY<STRING>, `full` ARRAY<STRUCT<id STRING, value STRING>>>, sdg_v1 STRUCT<codes ARRAY<STRING>, `full` ARRAY<STRUCT<id STRING, code STRING, name STRING>>>, uoa_v1 STRUCT<codes ARRAY<STRING>, `full` ARRAY<STRUCT<id STRING, code STRING, name STRING>>>, bra_v2020 STRUCT<values ARRAY<STRING>, `full` ARRAY<STRUCT<id STRING, value STRING>>>, for_v2020 STRUCT<first_level STRUCT<codes ARRAY<STRING>, `full` ARRAY<STRUCT<id STRING, code STRING, name STRING>>>, second_level STRUCT<codes ARRAY<STRING>, `full` ARRAY<STRUCT<id STRING, code STRING, name STRING>>>>, hrcs_hc_v2020 STRUCT<values ARRAY<STRING>, `full` ARRAY<STRUCT<id STRING, value STRING>>>, hrcs_rac_v2020 STRUCT<codes ARRAY<STRING>, `full` ARRAY<STRUCT<id STRING, code STRING, name STRING>>>, icrp_cso_v2020 STRUCT<codes ARRAY<STRING>, `full` ARRAY<STRUCT<id STRING, code STRING, name STRING>>>, icrp_ct_v2020 STRUCT<values ARRAY<STRING>, `full` ARRAY<STRUCT<id STRING, value STRING>>>, rcdc_v2020 STRUCT<values ARRAY<STRING>, `full` ARRAY<STRUCT<id STRING, value STRING>>>, for_2020_v2022 STRUCT<first_level STRUCT<codes ARRAY<STRING>, `full` ARRAY<STRUCT<id STRING, code STRING, name STRING>>>, second_level STRUCT<codes ARRAY<STRING>, `full` ARRAY<STRUCT<id STRING, code STRING, name STRING>>>>>,
  clinical_trial_ids ARRAY<STRING>,
  funding_details ARRAY<STRUCT<grant_id STRING, grid_id STRING>>,
  funder_orgs ARRAY<STRING>,
  document_type STRUCT<classification STRING, is_citable BOOL, versions STRUCT<v0 STRUCT<classification STRING, is_citable BOOL>>>,
  title STRUCT<preferred STRING, original STRING>,
  date_normal DATE,
  date_inserted TIMESTAMP,
  date_imported_gbq TIMESTAMP,
  patent_ids ARRAY<STRING>,
  citations ARRAY<STRUCT<id STRING, year INT64>>,
  citations_count INT64,
  journal STRUCT<id STRING, title STRING, issn STRING, eissn STRING>,
  journal_lists ARRAY<STRING>,
  parent_id STRING,
  source_id STRING,
  researcher_ids ARRAY<STRING>,
  research_orgs ARRAY<STRING>,
  research_org_cities ARRAY<INT64>,
  research_org_city_names ARRAY<STRING>,
  research_org_countries ARRAY<STRING>,
  research_org_country_names ARRAY<STRING>,
  research_org_state_codes ARRAY<STRING>,
  research_org_state_names ARRAY<STRING>,
  supporting_grant_ids ARRAY<STRING>,
  funder_countries ARRAY<STRING>,
  metrics STRUCT<times_cited INT64, recent_citations INT64, field_citation_ratio FLOAT64, relative_citation_ratio FLOAT64>,
  authors ARRAY<STRUCT<first_name STRING, last_name STRING, initials STRING, researcher_id STRING, grid_ids ARRAY<STRING>, orcid ARRAY<STRING>, corresponding BOOL, raw_affiliations ARRAY<STRING>, affiliations_address ARRAY<STRUCT<grid_id STRING, city_id INT64, state_code STRING, country_code STRING, raw_affiliation STRING>>>>,
  concepts ARRAY<STRUCT<concept STRING, relevance FLOAT64>>,
  altmetrics STRUCT<id STRING, score INT64>
);
