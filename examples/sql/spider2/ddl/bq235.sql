CREATE TABLE `bigquery-public-data.cms_medicare.inpatient_charges_2014`
(
  provider_id STRING NOT NULL OPTIONS(description="The CMS Certification Number (CCN) of the provider billing for outpatient hospital services"),
  provider_name STRING OPTIONS(description="The name of the provider"),
  provider_street_address STRING OPTIONS(description="The street address in which the provider is physically located"),
  provider_city STRING OPTIONS(description="The city in which the provider is physically located"),
  provider_state STRING OPTIONS(description="The state in which the provider is physically located"),
  provider_zipcode STRING OPTIONS(description="The zip code in which the provider is physically located"),
  drg_definition STRING NOT NULL OPTIONS(description="The code and description identifying the MS-DRG. MS-DRGs are a classification system that groups similar clinical conditions (diagnoses) and the procedures furnished by the hospital during the stay"),
  hospital_referral_region_description STRING OPTIONS(description="The Hospital Referral Region (HRR) in which the provider is physically located"),
  total_discharges INT64 OPTIONS(description="The number of discharges billed by the provider for inpatient hospital services"),
  average_covered_charges FLOAT64 OPTIONS(description="The provider's average charge for services covered by Medicare for all discharges in the MS-DRG. These will vary from hospital to hospital because of differences in hospital charge structures"),
  average_total_payments FLOAT64 OPTIONS(description="The average total payments to all providers for the MS-DRG including the MSDRG amount, teaching, disproportionate share, capital, and outlier payments for all cases. Also included 5 in average total payments are co-payment and deductible amounts that the patient is responsible for and any additional payments by third parties for coordination of benefits"),
  average_medicare_payments FLOAT64 OPTIONS(description="The average amount that Medicare pays to the provider for Medicare's share of the MS-DRG. Average Medicare payment amounts include the MS-DRG amount, teaching, disproportionate share, capital, and outlier payments for all cases. Medicare payments DO NOT include beneficiary co-payments and deductible amounts nor any additional payments from third parties for coordination of benefits")
);

CREATE TABLE `bigquery-public-data.cms_medicare.outpatient_charges_2014`
(
  provider_id STRING NOT NULL OPTIONS(description="The CMS Certification Number (CCN) of the provider billing for outpatient hospital services"),
  provider_name STRING OPTIONS(description="The name of the provider"),
  provider_street_address STRING OPTIONS(description="The street address in which the provider is physically located"),
  provider_city STRING OPTIONS(description="The city in which the provider is physically located"),
  provider_state STRING OPTIONS(description="The state in which the provider is physically located"),
  provider_zipcode STRING OPTIONS(description="The zip code in which the provider is physically located"),
  apc STRING NOT NULL OPTIONS(description="The code and description identifying the MS-DRG. MS-DRGs are a classification system that groups similar clinical conditions (diagnoses) and the procedures furnished by the hospital during the stay"),
  hospital_referral_region STRING OPTIONS(description="Code and description identifying the APC. APCs are a classification system where individual services (Healthcare Common Procedure Coding System [HCPCS] codes) are assigned based on similar clinical characteristics and similar costs"),
  outpatient_services INT64 OPTIONS(description="The number of discharges billed by the provider for inpatient hospital services"),
  average_estimated_submitted_charges FLOAT64 OPTIONS(description="The number of services billed by the provider for outpatient hospital services"),
  average_total_payments FLOAT64 OPTIONS(description="The provider's average estimated submitted charge for services covered by Medicare for the APC. These will vary from hospital to hospital because of differences in hospital charge structures")
);

CREATE TABLE `bigquery-public-data.cms_medicare.inpatient_charges`
(
  provider_id STRING NOT NULL OPTIONS(description="The CMS Certification Number (CCN) of the provider billing for outpatient hospital services"),
  provider_name STRING OPTIONS(description="The name of the provider"),
  provider_street_address STRING OPTIONS(description="The street address in which the provider is physically located"),
  provider_city STRING OPTIONS(description="The city in which the provider is physically located"),
  provider_state STRING OPTIONS(description="The state in which the provider is physically located"),
  provider_zipcode STRING OPTIONS(description="The zip code in which the provider is physically located"),
  drg_definition STRING NOT NULL OPTIONS(description="The code and description identifying the MS-DRG. MS-DRGs are a classification system that groups similar clinical conditions (diagnoses) and the procedures furnished by the hospital during the stay"),
  hospital_referral_region_description STRING OPTIONS(description="The Hospital Referral Region (HRR) in which the provider is physically located"),
  total_discharges INT64 OPTIONS(description="The number of discharges billed by the provider for inpatient hospital services"),
  average_covered_charges FLOAT64 OPTIONS(description="The provider's average charge for services covered by Medicare for all discharges in the MS-DRG. These will vary from hospital to hospital because of differences in hospital charge structures"),
  average_total_payments FLOAT64 OPTIONS(description="The average total payments to all providers for the MS-DRG including the MSDRG amount, teaching, disproportionate share, capital, and outlier payments for all cases. Also included 5 in average total payments are co-payment and deductible amounts that the patient is responsible for and any additional payments by third parties for coordination of benefits"),
  average_medicare_payments FLOAT64 OPTIONS(description="The average amount that Medicare pays to the provider for Medicare's share of the MS-DRG. Average Medicare payment amounts include the MS-DRG amount, teaching, disproportionate share, capital, and outlier payments for all cases. Medicare payments DO NOT include beneficiary co-payments and deductible amounts nor any additional payments from third parties for coordination of benefits")
);

CREATE TABLE `bigquery-public-data.cms_medicare.outpatient_charges`
(
  provider_id STRING NOT NULL OPTIONS(description="The CMS Certification Number (CCN) of the provider billing for outpatient hospital services"),
  provider_name STRING OPTIONS(description="The name of the provider"),
  provider_street_address STRING OPTIONS(description="The street address in which the provider is physically located"),
  provider_city STRING OPTIONS(description="The city in which the provider is physically located"),
  provider_state STRING OPTIONS(description="The state in which the provider is physically located"),
  provider_zipcode INT64 OPTIONS(description="The zip code in which the provider is physically located"),
  apc STRING NOT NULL OPTIONS(description="Code and description identifying the APC. APCs are a classification system where individual services (Healthcare Common Procedure Coding System [HCPCS] codes) are assigned based on similar clinical characteristics and similar costs"),
  hospital_referral_region STRING OPTIONS(description="The Hospital Referral Region (HRR) in which the provider is physically located"),
  outpatient_services INT64 OPTIONS(description="The number of services billed by the provider for outpatient hospital services"),
  average_estimated_submitted_charges FLOAT64 OPTIONS(description="The provider's average estimated submitted charge for services covered by Medicare for the APC. These will vary from hospital to hospital because of differences in hospital charge structures"),
  average_total_payments FLOAT64 OPTIONS(description="The average of total payments to the provider for the APC including the Medicare APC amount. Also included in Total Payments are co-payment and deductible amounts that the patient is responsible for")
);
