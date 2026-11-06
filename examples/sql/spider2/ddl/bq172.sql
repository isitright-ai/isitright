CREATE TABLE `bigquery-public-data.cms_medicare.part_d_prescriber_2014`
(
  npi STRING NOT NULL OPTIONS(description="National Provider Identifier"),
  nppes_provider_last_org_name STRING OPTIONS(description="Last Name/Organization Name of the Provider"),
  nppes_provider_first_name STRING OPTIONS(description="First Name of the Provider"),
  nppes_provider_city STRING OPTIONS(description="City of the Provider"),
  nppes_provider_state STRING OPTIONS(description="State Code of the Provider"),
  specialty_description STRING OPTIONS(description="Provider Specialty Type"),
  description_flag STRING OPTIONS(description="Source of Provider Specialty"),
  drug_name STRING NOT NULL OPTIONS(description="Name of the drug"),
  generic_name STRING OPTIONS(description="Generic name of the drug"),
  bene_count INT64 OPTIONS(description="Number of Medicare Beneficiaries"),
  total_claim_count INT64 OPTIONS(description="Number of Medicare Part D Claims, Including Refills"),
  total_day_supply INT64 OPTIONS(description="Number of Day's Supply for All Claims"),
  total_drug_cost FLOAT64 OPTIONS(description="Aggregate Cost Paid for All Claims"),
  bene_count_ge65 INT64 OPTIONS(description="Number of Medicare Beneficiaries Age 65+"),
  bene_count_ge65_suppress_flag STRING OPTIONS(description="Reason for Suppression of Bene_Count_ge65"),
  total_claim_count_ge65 INT64 OPTIONS(description="Number of Claims, Including Refills, for Beneficiaries Age 65+"),
  ge65_suppress_flag STRING OPTIONS(description="Reason for Suppression of Total_Claim_Count_Ge65, Total_Drug_Cost_Ge65, and Total_Day_Supply_Ge65"),
  total_day_supply_ge65 INT64 OPTIONS(description="Number of Day's Supply for All Claims for Beneficiaries Age 65+"),
  total_drug_cost_ge65 FLOAT64 OPTIONS(description="Aggregate Cost Paid for All Claims for Beneficiaries Age 65+"),
  total_30_day_fill_count FLOAT64 OPTIONS(description="The aggregate number of Medicare Part D standardized 30-day fills. The standardized 30-day fill is derived from the number of days supplied on each Part D claim divided by 30. Standardized 30-day fill values less than 1.0 were bottom-coded with a value of 1.0 and standardized 30- day fill values greater than 12.0 were top-coded with a value of 12.0."),
  total_30_day_fill_count_ge65 FLOAT64 OPTIONS(description="The number of Medicare Part D standardized 30-day fills for beneficiaries age 65 and older. The standardized 30-day fill is derived from the number of days supplied on each Part D claim divided by 30. Standardized 30-day fill values less than 1.0 were bottom-coded with a value of 1.0 and standardized 30-day fill values greater than 12.0 were top-coded with a value of 12.0.")
);
