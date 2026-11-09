CREATE TABLE `bigquery-public-data.census_bureau_acs.censustract_2011_5yr`
(
  geo_id STRING OPTIONS(description="US Census Tracts Geoids"),
  nonfamily_households FLOAT64 OPTIONS(description="Nonfamily Households. A householder living alone or with nonrelatives only. Unmarried couples households, whether opposite-sex or same-sex, with no relatives of the householder present are tabulated in nonfamily households."),
  family_households FLOAT64 OPTIONS(description="Family Households. A family consists of a householder and one or more other people living in the same household who are related to the householder by birth, marriage, or adoption. All people in a household who are related to the householder are regarded as members of his or her family. A family household may contain people not related to the householder, but those people are not included as part of the family of the householder in tabulations. Thus, the number of family households is equal to the number of families, but family households may include more members than do families. A household can contain only one family for purposes of tabulations. Not all households contain families since a household may be comprised of a group of unrelated people or of one person living alone -- these are called nonfamily households. Families are classified by type as either a \"married couple family\" or \"other family\" according to the sex of the householder and the presence of relatives. The data on family type are based ..."),
  median_year_structure_built FLOAT64 OPTIONS(description="Median Year Structure Built. Median Year Structure Built"),
  rent_burden_not_computed FLOAT64 OPTIONS(description="Housing units without rent burden computed. Units for which no rent is paid and units occupied by households that reported no income or a net loss comprise this category"),
  rent_over_50_percent FLOAT64 OPTIONS(description="Housing units spending over 50% income on rent. Gross rent over 50 percent of household income. Computed ratio of monthly gross rent to monthly household income (total household income divided by 12). The ratio is computed separately for each unit and is rounded to the nearest tenth. Units for which no rent is paid and units occupied by households that report no income or a net loss comprise the category, \"Not computed\". Gross rent as a percentage of household income provides information on the monthly housing cost expenses for renters. "),
  rent_40_to_50_percent FLOAT64 OPTIONS(description="Housing units spending 40 to 49.9% income on rent. Gross rent from 40.0 to 49.9 percent of household income. Computed ratio of monthly gross rent to monthly household income (total household income divided by 12). The ratio is computed separately for each unit and is rounded to the nearest tenth. Units for which no rent is paid and units occupied by households that report no income or a net loss comprise the category, \"Not computed\". Gross rent as a percentage of household income provides information on the monthly housing cost expenses for renters. "),
  rent_35_to_40_percent FLOAT64 OPTIONS(description="Housing units spending 35 to 39.9% income on rent. Gross rent from 35.0 to 39.9 percent of household income. Computed ratio of monthly gross rent to monthly household income (total household income divided by 12). The ratio is computed separately for each unit and is rounded to the nearest tenth. Units for which no rent is paid and units occupied by households that report no income or a net loss comprise the category, \"Not computed\". Gross rent as a percentage of household income provides information on the monthly housing cost expenses for renters. "),
  rent_30_to_35_percent FLOAT64 OPTIONS(description="Housing units spending 30 to 34.9% income on rent. Gross rent from 30.0 to 34.9 percent of household income. Computed ratio of monthly gross rent to monthly household income (total household income divided by 12). The ratio is computed separately for each unit and is rounded to the nearest tenth. Units for which no rent is paid and units occupied by households that report no income or a net loss comprise the category, \"Not computed\". Gross rent as a percentage of household income provides information on the monthly housing cost expenses for renters. "),
  rent_25_to_30_percent FLOAT64 OPTIONS(description="Housing units spending 25 to 29.9% income on rent. Gross rent from 25.0 to 29.9 percent of household income. Computed ratio of monthly gross rent to monthly household income (total household income divided by 12). The ratio is computed separately for each unit and is rounded to the nearest tenth. Units for which no rent is paid and units occupied by households that report no income or a net loss comprise the category, \"Not computed\". Gross rent as a percentage of household income provides information on the monthly housing cost expenses for renters. "),
  rent_20_to_25_percent FLOAT64 OPTIONS(description="Housing units spending 20 to 24.9% income on rent. Gross rent from 20.0 to 24.9 percent of household income. Computed ratio of monthly gross rent to monthly household income (total household income divided by 12). The ratio is computed separately for each unit and is rounded to the nearest tenth. Units for which no rent is paid and units occupied by households that report no income or a net loss comprise the category, \"Not computed\". Gross rent as a percentage of household income provides information on the monthly housing cost expenses for renters. "),
  rent_15_to_20_percent FLOAT64 OPTIONS(description="Housing units spending 15 to 19.9% income on rent. Gross rent from 15.0 to 19.9 percent of household income. Computed ratio of monthly gross rent to monthly household income (total household income divided by 12). The ratio is computed separately for each unit and is rounded to the nearest tenth. Units for which no rent is paid and units occupied by households that report no income or a net loss comprise the category, \"Not computed\". Gross rent as a percentage of household income provides information on the monthly housing cost expenses for renters. "),
  rent_10_to_15_percent FLOAT64 OPTIONS(description="Housing units spending 10 to 14.9% income on rent. Gross rent from 10.0 to 14.9 percent of household income. Computed ratio of monthly gross rent to monthly household income (total household income divided by 12). The ratio is computed separately for each unit and is rounded to the nearest tenth. Units for which no rent is paid and units occupied by households that report no income or a net loss comprise the category, \"Not computed\". Gross rent as a percentage of household income provides information on the monthly housing cost expenses for renters. "),
  rent_under_10_percent FLOAT64 OPTIONS(description="Housing units spending less than 10% on rent. Gross rent less than 10 percent of household income. Computed ratio of monthly gross rent to monthly household income (total household income divided by 12). The ratio is computed separately for each unit and is rounded to the nearest tenth. Units for which no rent is paid and units occupied by households that report no income or a net loss comprise the category, \"Not computed\". Gross rent as a percentage of household income provides information on the monthly housing cost expenses for renters. "),
  total_pop FLOAT64 OPTIONS(description="Total Population. The total number of all people living in a given geographic area.  This is a very useful catch-all denominator when calculating rates."),
  male_pop FLOAT64 OPTIONS(description="Male Population. The number of people within each geography who are male."),
  female_pop FLOAT64 OPTIONS(description="Female Population. The number of people within each geography who are female."),
  median_age FLOAT64 OPTIONS(description="Median Age. The median age of all people in a given geographic area."),
  white_pop FLOAT64 OPTIONS(description="White Population. The number of people identifying as white, non-Hispanic in each geography."),
  black_pop FLOAT64 OPTIONS(description="Black or African American Population. The number of people identifying as black or African American, non-Hispanic in each geography."),
  asian_pop FLOAT64 OPTIONS(description="Asian Population. The number of people identifying as Asian, non-Hispanic in each geography."),
  hispanic_pop FLOAT64 OPTIONS(description="Hispanic Population. The number of people identifying as Hispanic or Latino in each geography."),
  amerindian_pop FLOAT64 OPTIONS(description="American Indian and Alaska Native Population. The number of people identifying as American Indian or Alaska native in each geography."),
  other_race_pop FLOAT64 OPTIONS(description="Other Race population. The number of people identifying as another race in each geography"),
  two_or_more_races_pop FLOAT64 OPTIONS(description="Two or more races population. The number of people identifying as two or more races in each geography"),
  not_hispanic_pop FLOAT64 OPTIONS(description="Population not Hispanic. The number of people not identifying as Hispanic or Latino in each geography."),
  commuters_by_public_transportation FLOAT64 OPTIONS(description="Commuters by Public Transportation. The number of workers age 16 years and over within a geographic area who primarily traveled to work by public transportation.  This is the principal mode of travel or type of conveyance, by distance rather than time, that the worker usually used to get from home to work."),
  households FLOAT64 OPTIONS(description="Households. A count of the number of households in each geography. A household consists of one or more people who live in the same dwelling and also share at meals or living accommodation, and may consist of a single family or some other grouping of people. "),
  median_income FLOAT64 OPTIONS(description="Median Household Income in the past 12 Months. Within a geographic area, the median income received by every household on a regular basis before payments for personal income taxes, social security, union dues, medicare deductions, etc.  It includes income received from wages, salary, commissions, bonuses, and tips; self-employment income from own nonfarm or farm businesses, including proprietorships and partnerships; interest, dividends, net rental income, royalty income, or income from estates and trusts; Social Security or Railroad Retirement income; Supplemental Security Income (SSI); any cash public assistance or welfare payments from the state or local welfare office; retirement, survivor, or disability benefits; and any other sources of income received regularly such as Veterans' (VA) payments, unemployment and/or worker's compensation, child support, and alimony."),
  income_per_capita FLOAT64 OPTIONS(description="Per Capita Income in the past 12 Months. Per capita income is the mean income computed for every man, woman, and child in a particular group. It is derived by dividing the total income of a particular group by the total population."),
  housing_units FLOAT64 OPTIONS(description="Housing Units. A count of housing units in each geography.  A housing unit is a house, an apartment, a mobile home or trailer, a group of rooms, or a single room occupied as separate living quarters, or if vacant, intended for occupancy as separate living quarters."),
  vacant_housing_units FLOAT64 OPTIONS(description="Vacant Housing Units. The count of vacant housing units in a geographic area. A housing unit is vacant if no one is living in it at the time of enumeration, unless its occupants are only temporarily absent. Units temporarily occupied at the time of enumeration entirely by people who have a usual residence elsewhere are also classified as vacant."),
  vacant_housing_units_for_rent FLOAT64 OPTIONS(description="Vacant Housing Units for Rent. The count of vacant housing units in a geographic area that are for rent. A housing unit is vacant if no one is living in it at the time of enumeration, unless its occupants are only temporarily absent. Units temporarily occupied at the time of enumeration entirely by people who have a usual residence elsewhere are also classified as vacant."),
  vacant_housing_units_for_sale FLOAT64 OPTIONS(description="Vacant Housing Units for Sale. The count of vacant housing units in a geographic area that are for sale. A housing unit is vacant if no one is living in it at the time of enumeration, unless its occupants are only temporarily absent. Units temporarily occupied at the time of enumeration entirely by people who have a usual residence elsewhere are also classified as vacant."),
  median_rent FLOAT64 OPTIONS(description="Median Rent. The median contract rent within a geographic area. The contract rent is the monthly rent agreed to or contracted for, regardless of any furnishings, utilities, fees, meals, or services that may be included. For vacant units, it is the monthly rent asked for the rental unit at the time of interview."),
  percent_income_spent_on_rent FLOAT64 OPTIONS(description="Percent of Household Income Spent on Rent. Within a geographic area, the median percentage of household income which was spent on gross rent.  Gross rent is the amount of the contract rent plus the estimated average monthly cost of utilities (electricity, gas, water, sewer etc.) and fuels (oil, coal, wood, etc.) if these are paid by the renter.  Household income is the sum of the income of all people 15 years and older living in the household."),
  owner_occupied_housing_units FLOAT64 OPTIONS(description="Owner-occupied Housing Units"),
  million_dollar_housing_units FLOAT64 OPTIONS(description="Owner-occupied Housing Units valued at $1,000,000 or more.. The count of owner occupied housing units in a geographic area that are valued at $1,000,000 or more.  Value is the respondent's estimate of how much the property (house and lot, mobile home and lot, or condominium unit) would sell for if it were for sale."),
  mortgaged_housing_units FLOAT64 OPTIONS(description="Owner-occupied Housing Units with a Mortgage. The count of housing units within a geographic area that are mortagaged. \"Mortgage\" refers to all forms of debt where the property is pledged as security for repayment of the debt, including deeds of trust, trust deed, contracts to purchase, land contracts, junior mortgages, and home equity loans."),
  families_with_young_children FLOAT64 OPTIONS(description="Families with young children (under 6 years of age)"),
  two_parent_families_with_young_children FLOAT64 OPTIONS(description="Two-parent families with young children (under 6 years of age)"),
  two_parents_in_labor_force_families_with_young_children FLOAT64 OPTIONS(description="Two-parent families, both parents in labor force with young children (under 6 years of age)"),
  two_parents_father_in_labor_force_families_with_young_children FLOAT64 OPTIONS(description="Two-parent families, father only in labor force with young children (under 6 years of age)"),
  two_parents_mother_in_labor_force_families_with_young_children FLOAT64 OPTIONS(description="Two-parent families, mother only in labor force with young children (under 6 years of age)"),
  two_parents_not_in_labor_force_families_with_young_children FLOAT64 OPTIONS(description="Two-parent families, neither parent in labor force with young children (under 6 years of age)"),
  one_parent_families_with_young_children FLOAT64 OPTIONS(description="One-parent families with young children (under 6 years of age)"),
  father_one_parent_families_with_young_children FLOAT64 OPTIONS(description="One-parent families, father, with young children (under 6 years of age)"),
  father_in_labor_force_one_parent_families_with_young_children FLOAT64 OPTIONS(description="One-parent families, father in labor force, with young children (under 6 years of age)"),
  commute_10_14_mins FLOAT64 OPTIONS(description="Number of workers with a commute between 10 and 14 minutes. The number of workers in a geographic area over the age of 16 who do not work from home and commute in between 10 and 14 minutes. "),
  commute_15_19_mins FLOAT64 OPTIONS(description="Number of workers with a commute between 15 and 19 minutes. The number of workers in a geographic area over the age of 16 who do not work from home and commute in between 15 and 19 minutes. "),
  commute_20_24_mins FLOAT64 OPTIONS(description="Number of workers with a commute between 20 and 24 minutes. The number of workers in a geographic area over the age of 16 who do not work from home and commute in between 20 and 24 minutes."),
  commute_25_29_mins FLOAT64 OPTIONS(description="Number of workers with a commute between 25 and 29 minutes. The number of workers in a geographic area over the age of 16 who do not work from home and commute in between 25 and 29 minutes. "),
  commute_30_34_mins FLOAT64 OPTIONS(description="Number of workers with a commute between 30 and 34 minutes. The number of workers in a geographic area over the age of 16 who do not work from home and commute in between 30 and 34 minutes. "),
  commute_45_59_mins FLOAT64 OPTIONS(description="Number of workers with a commute between 45 and 59 minutes. The number of workers in a geographic area over the age of 16 who do not work from home and commute in between 45 and 59 minutes. "),
  aggregate_travel_time_to_work FLOAT64 OPTIONS(description="Aggregate travel time to work. The total number of minutes every worker in a geographic area over the age of 16 who did not work from home spent spent commuting to work in one day"),
  income_less_10000 FLOAT64 OPTIONS(description="Households with income less than $10,000. The number of households in a geographic area whose annual income was less than $10,000."),
  income_10000_14999 FLOAT64 OPTIONS(description="Households with income of $10,000 to $14,999. The number of households in a geographic area whose annual income was between $10,000 and $14,999."),
  income_15000_19999 FLOAT64 OPTIONS(description="Households with income of $15,000 to $19,999. The number of households in a geographic area whose annual income was between $15,000 and $19,999."),
  income_20000_24999 FLOAT64 OPTIONS(description="Households with income of $20,000 to $24,999. The number of households in a geographic area whose annual income was between $20,000 and $24,999."),
  income_25000_29999 FLOAT64 OPTIONS(description="Households with income of $25,000 to $29,999. The number of households in a geographic area whose annual income was between $20,000 and $24,999."),
  income_30000_34999 FLOAT64 OPTIONS(description="Households with income of $30,000 to $34,999. The number of households in a geographic area whose annual income was between $30,000 and $34,999."),
  income_35000_39999 FLOAT64 OPTIONS(description="Households with income of $35,000 to $39,999. The number of households in a geographic area whose annual income was between $35,000 and $39,999."),
  income_40000_44999 FLOAT64 OPTIONS(description="Households with income of $40,000 to $44,999. The number of households in a geographic area whose annual income was between $40,000 and $44,999."),
  income_45000_49999 FLOAT64 OPTIONS(description="Households with income of $45,000 to $49,999. The number of households in a geographic area whose annual income was between $45,000 and $49,999."),
  income_50000_59999 FLOAT64 OPTIONS(description="Households with income of $50,000 to $59,999. The number of households in a geographic area whose annual income was between $50,000 and $59,999."),
  income_60000_74999 FLOAT64 OPTIONS(description="Households with income of $60,000 to $74,999. The number of households in a geographic area whose annual income was between $60,000 and $74,999."),
  income_75000_99999 FLOAT64 OPTIONS(description="Households with income of $75,000 to $99,999. The number of households in a geographic area whose annual income was between $75,000 and $99,999."),
  income_100000_124999 FLOAT64 OPTIONS(description="Households with income of $100,000 to $124,999. The number of households in a geographic area whose annual income was between $100,000 and $124,999."),
  income_125000_149999 FLOAT64 OPTIONS(description="Households with income of $125,000 to $149,999. The number of households in a geographic area whose annual income was between $125,000 and $149,999."),
  income_150000_199999 FLOAT64 OPTIONS(description="Households with income of $150,000 to $199,999. The number of households in a geographic area whose annual income was between $150,000 and $1999,999."),
  income_200000_or_more FLOAT64 OPTIONS(description="Households with income of $200,000 Or More. The number of households in a geographic area whose annual income was more than $200,000."),
  renter_occupied_housing_units_paying_cash_median_gross_rent FLOAT64 OPTIONS(description="Renter-Occupied Housing Units Paying Cash Rent Median Gross Rent"),
  owner_occupied_housing_units_lower_value_quartile FLOAT64 OPTIONS(description="Owner-Occupied Housing Units Lower Value Quartile"),
  owner_occupied_housing_units_median_value FLOAT64 OPTIONS(description="Owner-Occupied Housing Units Median Value. The middle value (median) in a geographic area owner occupied housing units."),
  owner_occupied_housing_units_upper_value_quartile FLOAT64 OPTIONS(description="Owner-Occupied Housing Units Upper Value Quartile"),
  married_households FLOAT64 OPTIONS(description="Married households. People in formal marriages, as well as people in common-law marriages, are included. Does not include same-sex marriages."),
  occupied_housing_units FLOAT64 OPTIONS(description="Occupied housing units. A housing unit is classified as occupied if it is the usual place of residence of the person or group of people living in it at the time of enumeration."),
  housing_units_renter_occupied FLOAT64 OPTIONS(description="Renter occupied housing units. All occupied units which are not owner occupied, whether they are rented for cash rent or occupied without payment of cash rent, are classified as renter-occupied."),
  dwellings_1_units_detached FLOAT64 OPTIONS(description="Single-family (one unit) detached dwellings. This is a 1-unit structure detached from any other house, that is, with open space on all four sides. Such structures are considered detached even if they have an adjoining shed or garage. A one-family house that contains a business is considered detached as long as the building has open space on all four sides. Mobile homes to which one or more permanent rooms have been added or built also are included."),
  dwellings_1_units_attached FLOAT64 OPTIONS(description="Single-family (one unit) attached dwellings. This is a 1-unit structure that has one or more walls extending from ground to roof separating it from adjoining structures. In row houses (sometimes called townhouses), double houses, or houses attached to nonresidential structures, each house is a separate, attached structure if the dividing or common wall goes from ground to roof."),
  dwellings_2_units FLOAT64 OPTIONS(description="Two-family (two unit) dwellings"),
  dwellings_3_to_4_units FLOAT64 OPTIONS(description="Multifamily dwellings with three to 4 units"),
  dwellings_5_to_9_units FLOAT64 OPTIONS(description="Apartment buildings with 5 to 9 units"),
  dwellings_10_to_19_units FLOAT64 OPTIONS(description="Apartment buildings with 10 to 19 units"),
  dwellings_20_to_49_units FLOAT64 OPTIONS(description="Apartment buildings with 20 to 49 units"),
  dwellings_50_or_more_units FLOAT64 OPTIONS(description="Apartment buildings with 50 or more units"),
  mobile_homes FLOAT64 OPTIONS(description="Mobile homes. A manufactured home is defined as a movable dwelling, 8 feet or more wide and 40 feet or more long, designed to be towed on its own chassis, with transportation gear integral to the unit when it leaves the factory, and without need of a permanent foundation. These homes are built in accordance with the U.S. Department of Housing and Urban Development (HUD) building code."),
  housing_built_2005_or_later FLOAT64 OPTIONS(description="Housing units built in 2005 or later. A house, an apartment, a mobile home or trailer, a group of rooms, or a single room occupied as separate living quarters, or if vacant, intended for occupancy as separate living quarters built in 2005 or later."),
  housing_built_2000_to_2004 FLOAT64 OPTIONS(description="Housing units built between 2000 and 2004. A house, an apartment, a mobile home or trailer, a group of rooms, or a single room occupied as separate living quarters, or if vacant, intended for occupancy as separate living quarters built from 2000 to 2004."),
  housing_built_1939_or_earlier FLOAT64 OPTIONS(description="Housing units built before 1939. A house, an apartment, a mobile home or trailer, a group of rooms, or a single room occupied as separate living quarters, or if vacant, intended for occupancy as separate living quarters built in 1939 or earlier."),
  male_under_5 FLOAT64 OPTIONS(description="Male under 5 years. The male population over the age of five years within the specified area."),
  male_5_to_9 FLOAT64 OPTIONS(description="Male age 5 to 9. The male population between the age of five years to nine years within the specified area."),
  male_10_to_14 FLOAT64 OPTIONS(description="Male age 10 to 14. The male population between the age of ten years to fourteen years within the specified area."),
  male_15_to_17 FLOAT64 OPTIONS(description="Male age 15 to 17. The male population between the age of fifteeen years to seventeen years within the specified area."),
  male_18_to_19 FLOAT64 OPTIONS(description="Male age 18 and 19. The male population between the age of eighteen years to nineteen years within the specified area."),
  male_20 FLOAT64 OPTIONS(description="Male age 20. The male population with an age of twenty years within the specified area."),
  male_21 FLOAT64 OPTIONS(description="Male age 21. The male population with an age of twenty-one years within the specified area."),
  male_22_to_24 FLOAT64 OPTIONS(description="Male age 22 to 24. The male population between the age of twenty-two years to twenty-four years within the specified area."),
  male_25_to_29 FLOAT64 OPTIONS(description="Male age 25 to 29. The male population between the age of twenty-five years to twenty-nine years within the specified area."),
  male_30_to_34 FLOAT64 OPTIONS(description="Male age 30 to 34. The male population between the age of thirty years to thirty-four years within the specified area."),
  male_35_to_39 FLOAT64 OPTIONS(description="Male age 35 to 39. The male population between the age of thirty-five years to thirty-nine years within the specified area."),
  male_40_to_44 FLOAT64 OPTIONS(description="Male age 40 to 44. The male population between the age of fourty years to fourty-four years within the specified area."),
  male_45_to_49 FLOAT64 OPTIONS(description="Men age 45 to 49. The male population between the age of fourty-five years to fourty-nine years within the specified area."),
  male_50_to_54 FLOAT64 OPTIONS(description="Men age 50 to 54. The male population between the age of fifty years to fifty-four years within the specified area."),
  male_55_to_59 FLOAT64 OPTIONS(description="Men age 55 to 59. The male population between the age of fifty-five years to fifty-nine years within the specified area."),
  male_60_61 FLOAT64 OPTIONS(description="Men age 60 to 61. The male population between the age of sixty years to sixty-one years within the specified area."),
  male_62_64 FLOAT64 OPTIONS(description="Men age 62 to 64. The male population between the age of sixty-two years to sixty-four years within the specified area."),
  male_65_to_66 FLOAT64 OPTIONS(description="Male age 65 to 66. The male population between the age of sixty-five years to sixty-six years within the specified area."),
  male_67_to_69 FLOAT64 OPTIONS(description="Male age 67 to 69. The male population between the age of sixty-seven years to sixty-nine years within the specified area."),
  male_70_to_74 FLOAT64 OPTIONS(description="Male age 70 to 74. The male population between the age of seventy years to seventy-four years within the specified area."),
  male_75_to_79 FLOAT64 OPTIONS(description="Male age 75 to 79. The male population between the age of seventy-five years to seventy-nine years within the specified area."),
  male_80_to_84 FLOAT64 OPTIONS(description="Male age 80 to 84. The male population between the age of eighty years to eighty-four years within the specified area."),
  male_85_and_over FLOAT64 OPTIONS(description="Male age 85 and over. The male population of the age of eighty-five years and over within the specified area."),
  female_under_5 FLOAT64 OPTIONS(description="Female under 5 years. The female population over the age of five years within the specified area."),
  female_5_to_9 FLOAT64 OPTIONS(description="Female age 5 to 9. The female population between the age of five years to nine years within the specified area."),
  female_10_to_14 FLOAT64 OPTIONS(description="Female age 10 to 14. The female population between the age of ten years to fourteen years within the specified area."),
  female_15_to_17 FLOAT64 OPTIONS(description="Female age 15 to 17. The female population between the age of fifteeen years to seventeen years within the specified area."),
  female_18_to_19 FLOAT64 OPTIONS(description="Female age 18 and 19. The female population between the age of eighteen years to nineteen years within the specified area."),
  female_20 FLOAT64 OPTIONS(description="Female age 20. The female population with an age of twenty years within the specified area."),
  female_21 FLOAT64 OPTIONS(description="Female age 21. The female population with an age of twenty-one years within the specified area."),
  female_22_to_24 FLOAT64 OPTIONS(description="Female age 22 to 24. The female population between the age of twenty-two years to twenty-four years within the specified area."),
  female_25_to_29 FLOAT64 OPTIONS(description="Female age 25 to 29. The female population between the age of twenty-five years to twenty-nine years within the specified area."),
  female_30_to_34 FLOAT64 OPTIONS(description="Female age 30 to 34. The female population between the age of thirty years to thirty-four years within the specified area."),
  female_35_to_39 FLOAT64 OPTIONS(description="Female age 35 to 39. The female population between the age of thirty-five years to thirty-nine years within the specified area."),
  female_40_to_44 FLOAT64 OPTIONS(description="Female age 40 to 44. The female population between the age of fourty years to fourty-four years within the specified area."),
  female_45_to_49 FLOAT64 OPTIONS(description="Female age 45 to 49. The female population between the age of fourty-five years to fourty-nine years within the specified area."),
  female_50_to_54 FLOAT64 OPTIONS(description="Female age 50 to 54. The female population between the age of fifty years to fifty-four years within the specified area."),
  female_55_to_59 FLOAT64 OPTIONS(description="Female age 55 to 59. The female population between the age of fifty-five years to fifty-nine years within the specified area."),
  female_60_to_61 FLOAT64 OPTIONS(description="Female age 60 and 61. The female population between the age of sixty years to sixty-one years within the specified area."),
  female_62_to_64 FLOAT64 OPTIONS(description="Female age 62 to 64. The female population between the age of sixty-two years to sixty-four years within the specified area."),
  female_65_to_66 FLOAT64 OPTIONS(description="Female age 65 to 66. The female population between the age of sixty-five years to sixty-six years within the specified area."),
  female_67_to_69 FLOAT64 OPTIONS(description="Female age 67 to 69. The female population between the age of sixty-seven years to sixty-nine years within the specified area."),
  female_70_to_74 FLOAT64 OPTIONS(description="Female age 70 to 74. The female population between the age of seventy years to seventy-four years within the specified area."),
  female_75_to_79 FLOAT64 OPTIONS(description="Female age 75 to 79. The female population between the age of seventy-five years to seventy-nine years within the specified area."),
  female_80_to_84 FLOAT64 OPTIONS(description="Female age 80 to 84. The female population between the age of eighty years to eighty-four years within the specified area."),
  female_85_and_over FLOAT64 OPTIONS(description="Female age 85 and over. The female population of the age of eighty-five years and over within the specified area."),
  white_including_hispanic FLOAT64 OPTIONS(description="White including Hispanic"),
  black_including_hispanic FLOAT64 OPTIONS(description="Black including Hispanic"),
  amerindian_including_hispanic FLOAT64 OPTIONS(description="American Indian including Hispanic"),
  asian_including_hispanic FLOAT64 OPTIONS(description="Asian including Hispanic"),
  commute_5_9_mins FLOAT64 OPTIONS(description="Number of workers with a commute between 5 and 9 minutes. The number of workers in a geographic area over the age of 16 who do not work from home and commute in between 5 and 9 minutes."),
  commute_35_39_mins FLOAT64 OPTIONS(description="Number of workers with a commute between 35 and 39 minutes. The number of workers in a geographic area over the age of 16 who do not work from home and commute in between 35 and 39 minutes. "),
  commute_40_44_mins FLOAT64 OPTIONS(description="Number of workers with a commute between 40 and 44 minutes. The number of workers in a geographic area over the age of 16 who do not work from home and commute in between 40 and 44 minutes. "),
  commute_60_89_mins FLOAT64 OPTIONS(description="Number of workers with a commute between 60 and 89 minutes. The number of workers in a geographic area over the age of 16 who do not work from home and commute in between 60 and 89 minutes ."),
  commute_90_more_mins FLOAT64 OPTIONS(description="Number of workers with a commute of more than 90 minutes. The number of workers in a geographic area over the age of 16 who do not work from home and commute more than 90 minutes."),
  households_retirement_income FLOAT64 OPTIONS(description="Households receiving retirement income"),
  armed_forces FLOAT64 OPTIONS(description="Population in Armed Forces. The number of people in each geography who are members of the U.S. Armed Forces (people on active duty with the United States Army, Air Force, Navy, Marine Corps, or Coast Guard)."),
  civilian_labor_force FLOAT64 OPTIONS(description="Population in Civilian Labor Force. The number of civilians 16 years and over in each geography who can be classified as either \"employed\" or \"unemployed\" below."),
  employed_pop FLOAT64 OPTIONS(description="Employed Population. The number of civilians 16 years old and over in each geography who either (1) were \"at work,\" that is, those who did any work at all during the reference week as paid employees, worked in their own business or profession, worked on their own farm, or worked 15 hours or more as unpaid workers on a family farm or in a family business; or (2) were \"with a job but not at work,\" that is, those who did not work during the reference week but had jobs or businesses from which they were temporarily absent due to illness, bad weather, industrial dispute, vacation, or other personal reasons. Excluded from the employed are people whose only activity consisted of work around the house or unpaid volunteer work for religious, charitable, and similar organizations; also excluded are all institutionalized people and people on active duty in the United States Armed Forces."),
  unemployed_pop FLOAT64 OPTIONS(description=""),
  not_in_labor_force FLOAT64 OPTIONS(description="Population Not in Labor Force. The number of people in each geography who are 16 years old and over who are not classified as members of the labor force. This category consists mainly of students, homemakers, retired workers, seasonal workers interviewed in an off season who were not looking for work, institutionalized people, and people doing only incidental unpaid family work (less than 15 hours during the reference week)."),
  pop_16_over FLOAT64 OPTIONS(description="Population age 16 and over. The number of people in each geography who are age 16 or over."),
  pop_in_labor_force FLOAT64 OPTIONS(description="Population in Labor Force. The number of people in each geography who are either in the civilian labor force or are members of the U.S. Armed Forces (people on active duty with the United States Army, Air Force, Navy, Marine Corps, or Coast Guard)."),
  asian_male_45_54 FLOAT64 OPTIONS(description="Asian Men age 45 to 54"),
  asian_male_55_64 FLOAT64 OPTIONS(description="Asian Men age 55 to 64"),
  black_male_45_54 FLOAT64 OPTIONS(description="Black Men age 45 to 54"),
  black_male_55_64 FLOAT64 OPTIONS(description="Black Men age 55 to 64"),
  hispanic_male_45_54 FLOAT64 OPTIONS(description="Hispanic Men age 45 to 54"),
  hispanic_male_55_64 FLOAT64 OPTIONS(description="Hispanic Men age 55 to 64"),
  white_male_45_54 FLOAT64 OPTIONS(description="White Men age 45 to 54"),
  white_male_55_64 FLOAT64 OPTIONS(description="White Men age 55 to 64"),
  bachelors_degree_2 FLOAT64 OPTIONS(description="Population who completed a bachelor's degree. From mobility table."),
  bachelors_degree_or_higher_25_64 FLOAT64 OPTIONS(description="Population with Bachelors Degree or Higher, Ages 25 to 64. The number of people in each geography who are between the ages of 25 and 64 who have attained a bachelors degree or higher. "),
  children FLOAT64 OPTIONS(description="Children under 18 Years of Age. The number of people within each geography who are under 18 years of age."),
  children_in_single_female_hh FLOAT64 OPTIONS(description="Children under 18 years of age in single female-led household"),
  commuters_by_bus FLOAT64 OPTIONS(description="Commuters by Bus. The number of workers age 16 years and over within a geographic area who primarily traveled to work by bus.  This is the principal mode of travel or type of conveyance, by distance rather than time, that the worker usually used to get from home to work.  This is a subset of workers who commuted by public transport."),
  commuters_by_car_truck_van FLOAT64 OPTIONS(description="Commuters by Car, Truck, or Van. The number of workers age 16 years and over within  a geographic area who primarily traveled to work by car, truck or  van.  This is the principal mode of travel or type of conveyance,  by distance rather than time, that the worker usually used to get  from home to work."),
  commuters_by_carpool FLOAT64 OPTIONS(description="Commuters by Carpool. The number of workers age 16 years and over within a geographic area who primarily traveled to work by carpool.  This is the principal mode of travel or type of conveyance, by distance rather than time, that the worker usually used to get from home to work."),
  commuters_by_subway_or_elevated FLOAT64 OPTIONS(description="Commuters by Subway or Elevated. The number of workers age 16 years and over within a geographic area who primarily traveled to work by subway or elevated train.  This is the principal mode of travel or type of conveyance, by distance rather than time, that the worker usually used to get from home to work.  This is a subset of workers who commuted by public transport."),
  commuters_drove_alone FLOAT64 OPTIONS(description="Commuters who drove alone. The number of workers age 16 years and over within a geographic area who primarily traveled by car driving alone. This is the principal mode of travel or type of conveyance, by distance rather than time, that the worker usually used to get from home to work."),
  different_house_year_ago_different_city FLOAT64 OPTIONS(description="Lived in a different house one year ago in a different city. All people in a geographic area who lived in a different city within the year prior to the survey."),
  different_house_year_ago_same_city FLOAT64 OPTIONS(description="Lived in a different house one year ago in the same city. All people in a geographic area who lived in the same city but moved to a different unit within the year prior to the survey."),
  employed_agriculture_forestry_fishing_hunting_mining FLOAT64 OPTIONS(description="Workers employed in firms in agriculture, forestry, fishing, hunting, or mining. The Agriculture, Forestry, Fishing and Hunting sector comprises establishments primarily engaged in growing crops, raising animals, harvesting timber, and harvesting fish and other animals from a farm, ranch, or their natural habitats."),
  employed_arts_entertainment_recreation_accommodation_food FLOAT64 OPTIONS(description="Workers employed in firms in arts, entertainment, recreation, accommodation and food services. The Arts, Entertainment, and Recreation sector includes a wide range of establishments that operate facilities or provide services to meet varied cultural, entertainment, and recreational interests of their patrons. This sector comprises (1) establishments that are involved in producing, promoting, or participating in live performances, events, or exhibits intended for public viewing; (2) establishments that preserve and exhibit objects and sites of historical, cultural, or educational interest; and (3) establishments that operate facilities or provide services that enable patrons to participate in recreational activities or pursue amusement, hobby, and leisure-time interests."),
  employed_construction FLOAT64 OPTIONS(description="Workers employed in firms in construction. The Construction sector comprises establishments primarily engaged in the construction of buildings or engineering projects (e.g., highways and utility systems). Construction work done may include new work, additions, alterations, or maintenance and repairs."),
  employed_education_health_social FLOAT64 OPTIONS(description="Workers employed in firms in educational services, health care, and social assistance. Outpatient health services, other than hospital care, including: public health administration; research and education; categorical health programs; treatment and immunization clinics; nursing; environmental health activities such as air and water pollution control; ambulance service if provided separately from fire protection services, and other general public health activities such as mosquito abatement. School health services provided by health agencies (rather than school agencies) are included here. Sewage treatment operations are classified under Sewerage."),
  employed_finance_insurance_real_estate FLOAT64 OPTIONS(description="Workers employed in firms in finance, insurance, real estate and rental and leasing. The Real Estate and Rental and Leasing sector comprises establishments primarily engaged in renting, leasing, or otherwise allowing the use of tangible or intangible assets, and establishments providing related services. The major portion of this sector comprises establishments that rent, lease, or otherwise allow the use of their own assets by others. The assets may be tangible, as is the case of real estate and equipment, or intangible, as is the case with patents and trademarks."),
  employed_information FLOAT64 OPTIONS(description="Workers employed in firms in information. The Information sector comprises establishments engaged in the following processes: (a) producing and distributing information and cultural products, (b) providing the means to transmit or distribute these products as well as data or communications, and (c) processing data. Included are the publishing industries, the motion picture and sound recording industries; the broadcasting industries, the telecommunications industries; Web search portals, data processing industries, and the information services industries."),
  employed_manufacturing FLOAT64 OPTIONS(description="Workers employed in firms in manufacturing. The Manufacturing sector comprises establishments engaged in the mechanical, physical, or chemical transformation of materials, substances, or components into new products."),
  employed_other_services_not_public_admin FLOAT64 OPTIONS(description="Workers employed in firms in other services except public administration. The Other Services (Except Public Administration) sector comprises establishments engaged in providing services not specifically provided for elsewhere in the classification system. Establishments in this sector are primarily engaged in activities such as equipment and machinery repairing, promoting or administering religious activities, grantmaking, advocacy, and providing drycleaning and laundry services, personal care services, death care services, pet care services, photofinishing services, temporary parking services, and dating services. Private households that engage in employing workers on or about the premises in activities primarily concerned with the operation of the household are included in this sector."),
  employed_public_administration FLOAT64 OPTIONS(description="Workers employed in firms in public administration. The Public Administration sector consists of establishments of federal, state, and local government agencies that administer, oversee, and manage public programs and have executive, legislative, or judicial authority over other institutions within a given area. These agencies also set policy, create laws, adjudicate civil and criminal legal cases, provide for public safety and for national defense. In general, government establishments in the public administration sector oversee governmental programs and activities that are not performed by private establishments."),
  employed_retail_trade FLOAT64 OPTIONS(description="Workers employed in firms in retail trade. The Retail Trade sector comprises establishments engaged in retailing merchandise, generally without transformation, and rendering services incidental to the sale of merchandise. The retailing process is the final step in the distribution of merchandise; retailers are, therefore, organized to sell merchandise in small quantities to the general public."),
  employed_science_management_admin_waste FLOAT64 OPTIONS(description="Workers employed in firms in professional scientific, management, administrative and waste management services. The Administrative and Support and Waste Management and Remediation Services sector comprises establishments performing routine support activities for the day-to-day operations of other organizations. The establishments in this sector specialize in one or more of these support activities and provide these services to clients in a variety of industries and, in some cases, to households. Activities performed include office administration, hiring and placing of personnel, document preparation and similar clerical services, solicitation, collection, security and surveillance services, cleaning, and waste disposal services."),
  employed_transportation_warehousing_utilities FLOAT64 OPTIONS(description="Workers employed in firms in transportation, warehousing, and utilities. The Transportation and Warehousing sector includes industries providing transportation of passengers and cargo, warehousing and storage for goods, scenic and sightseeing transportation, and support activities related to modes of transportation. The modes of transportation are air, rail, water, road, and pipeline."),
  employed_wholesale_trade FLOAT64 OPTIONS(description="Workers employed in firms in wholesale trade. The Wholesale Trade sector comprises establishments engaged in wholesaling merchandise, generally without transformation, and rendering services incidental to the sale of merchandise. The wholesaling process is an intermediate step in the distribution of merchandise. Wholesalers are organized to sell or arrange the purchase or sale of (a) goods for resale (i.e., goods sold to other wholesalers or retailers), (b) capital or durable nonconsumer goods, and (c) raw and intermediate materials and supplies used in production."),
  female_female_households FLOAT64 OPTIONS(description="Households with two female partners. An unmarried partner is a person age 15 years and over, who is not related to the householder, who shares living quarters, and who has an intimate relationship with the householder."),
  four_more_cars FLOAT64 OPTIONS(description="Four car households. The number of households with four or more passenger cars, vans, pickup or panel trucks of one-ton capacity or less kept at home and available for the use of household members. Vehicles rented or leased for one month or more, company vehicles, and police and government vehicles are included if kept at home and used for non-business purposes. Dismantled or immobile vehicles ware excluded. Vehicles kept at home but used only for business purposes also are excluded."),
  gini_index FLOAT64 OPTIONS(description="Gini Index. The Gini index, or index of income concentration, is a statistical measure of income inequality ranging from 0 to 1. A measure of 1 indicates perfect inequality, i.e., one household having all the income and rest having none. A measure of 0 indicates perfect equality, i.e., all households having an equal share of income."),
  graduate_professional_degree FLOAT64 OPTIONS(description="Population who completed a graduate or professional degree"),
  group_quarters FLOAT64 OPTIONS(description="Population living in group quarters"),
  high_school_including_ged FLOAT64 OPTIONS(description="Population with high school degree, including GED. The number of people in a geographic area over the age of 25 who attained a high school degree or GED."),
  households_public_asst_or_food_stamps FLOAT64 OPTIONS(description="Households on cash public assistance or receiving food stamps (SNAP)"),
  in_grades_1_to_4 FLOAT64 OPTIONS(description="Students Enrolled in Grades 1 to 4. The total number of people in each geography currently enrolled in grades 1 through 4 inclusive.  This corresponds roughly to elementary school."),
  in_grades_5_to_8 FLOAT64 OPTIONS(description="Students Enrolled in Grades 5 to 8. The total number of people in each geography currently enrolled in grades 5 through 8 inclusive.  This corresponds roughly to middle school."),
  in_grades_9_to_12 FLOAT64 OPTIONS(description="Students Enrolled in Grades 9 to 12. The total number of people in each geography currently enrolled in grades 9 through 12 inclusive.  This corresponds roughly to high school."),
  in_school FLOAT64 OPTIONS(description="Students Enrolled in School. The total number of people in each geography currently enrolled at any level of school, from nursery or pre-school to advanced post-graduate education.  Only includes those over the age of 3."),
  in_undergrad_college FLOAT64 OPTIONS(description="Students Enrolled as Undergraduate in College. The number of people in a geographic area who are enrolled in college at the undergraduate level. Enrollment refers to being registered or listed as a student in an educational program leading to a college degree. This may be a public school or college, a private school or college."),
  less_than_high_school_graduate FLOAT64 OPTIONS(description="Less than high school graduate. The number of people in a geographic area over the age of 25 who have not completed high school or any other advanced degree."),
  male_45_64_associates_degree FLOAT64 OPTIONS(description="Men age 45 to 64 who obtained an associate's degree"),
  male_45_64_bachelors_degree FLOAT64 OPTIONS(description="Men age 45 to 64 who obtained a bachelor's degree"),
  male_45_64_graduate_degree FLOAT64 OPTIONS(description="Men age 45 to 64 who obtained a graduate or professional degree"),
  male_45_64_less_than_9_grade FLOAT64 OPTIONS(description="Men age 45 to 64 who attained less than a 9th grade education"),
  male_45_64_grade_9_12 FLOAT64 OPTIONS(description="Men age 45 to 64 who attained between 9th and 12th grade, no diploma"),
  male_45_64_high_school FLOAT64 OPTIONS(description="Men age 45 to 64 who completed high school or obtained GED"),
  male_45_64_some_college FLOAT64 OPTIONS(description="Men age 45 to 64 who completed some college, no degree"),
  male_45_to_64 FLOAT64 OPTIONS(description="Men age 45 to 64 (\"middle aged\"). The male population between the age of fourty-five years to sixty-four years within the specified area."),
  male_male_households FLOAT64 OPTIONS(description="Households with two male partners. An unmarried partner is a person age 15 years and over, who is not related to the householder, who shares living quarters, and who has an intimate relationship with the householder."),
  management_business_sci_arts_employed FLOAT64 OPTIONS(description="Civilian Employed Population in Management, Business, Science, and Arts Occupations. The number of employed civilians 16 years old and over in each geography in the Management, Business, Science, and Arts occupations. Occupation codes are based on the Standard Occupational Classification (SOC), published by the Executive Office of the President, Office of Management and Budget."),
  no_car FLOAT64 OPTIONS(description="Workers age 16 and over with no vehicle. All people in a geographic area over the age of 16 who do not own a car."),
  no_cars FLOAT64 OPTIONS(description="Car-free households. The number of households without passenger cars, vans, and pickup or panel trucks of one-ton capacity or less kept at home and available for the use of household members. Vehicles rented or leased for one month or more, company vehicles, and police and government vehicles are included if kept at home and used for non-business purposes. Dismantled or immobile vehicles ware excluded. Vehicles kept at home but used only for business purposes also are excluded."),
  not_us_citizen_pop FLOAT64 OPTIONS(description="Not a U.S. Citizen Population. The number of people within each geography who indicated that they are not U.S. citizens."),
  occupation_management_arts FLOAT64 OPTIONS(description="Workers employed in management business science and arts occupations"),
  occupation_natural_resources_construction_maintenance FLOAT64 OPTIONS(description="Workers employed in natural resources, construction, and maintenance occupations"),
  occupation_production_transportation_material FLOAT64 OPTIONS(description="Workers employed in production, transportation, and material moving"),
  occupation_sales_office FLOAT64 OPTIONS(description="Workers employed in sales and office occupations"),
  occupation_services FLOAT64 OPTIONS(description="Workers employed in service occupations"),
  one_car FLOAT64 OPTIONS(description="One car households. The number of households with one passenger car, van, , pickup or panel trucks of one-ton capacity or less kept at home and available for the use of household members. Vehicles rented or leased for one month or more, company vehicles, and police and government vehicles are included if kept at home and used for non-business purposes. Dismantled or immobile vehicles ware excluded. Vehicles kept at home but used only for business purposes also are excluded."),
  two_cars FLOAT64 OPTIONS(description="Two car households. The number of households with two passenger cars, vans, pickup or panel trucks of one-ton capacity or less kept at home and available for the use of household members. Vehicles rented or leased for one month or more, company vehicles, and police and government vehicles are included if kept at home and used for non-business purposes. Dismantled or immobile vehicles ware excluded. Vehicles kept at home but used only for business purposes also are excluded."),
  three_cars FLOAT64 OPTIONS(description="Three car households. The number of households with one passenger cars, vans, pickup or panel trucks of one-ton capacity or less kept at home and available for the use of household members. Vehicles rented or leased for one month or more, company vehicles, and police and government vehicles are included if kept at home and used for non-business purposes. Dismantled or immobile vehicles ware excluded. Vehicles kept at home but used only for business purposes also are excluded."),
  pop_25_64 FLOAT64 OPTIONS(description="Population age 25 to 64. The number of people in each geography who are between the ages of 25 and 64. "),
  pop_determined_poverty_status FLOAT64 OPTIONS(description="Population for Whom Poverty Status Determined. The number of people in each geography who could be identified as either living in poverty or not.  This should be used as the denominator when calculating poverty rates, as it excludes people for whom it was not possible to determine poverty."),
  population_1_year_and_over FLOAT64 OPTIONS(description="Population 1 year and over. All people, male and female, child and adult, living in a given geographic area that are 1 year and older."),
  population_3_years_over FLOAT64 OPTIONS(description="Population 3 Years and Over. The total number of people in each geography age 3 years and over.  This denominator is mostly used to calculate rates of school enrollment."),
  poverty FLOAT64 OPTIONS(description="Income In The Past 12 Months Below Poverty Level. The number of people in a geographic area who are part of a family (which could be just them as an individual) determined to be \"in poverty\" following the Office of Management and Budget's Directive 14. (https://www.census.gov/hhes/povmeas/methodology/ombdir14.html)"),
  sales_office_employed FLOAT64 OPTIONS(description="Civilian Employed Population in Sales and Office Occupations. The number of employed civilians 16 years old and over in each geography in the Sales and Office occupations. Occupation codes are based on the Standard Occupational Classification (SOC), published by the Executive Office of the President, Office of Management and Budget."),
  some_college_and_associates_degree FLOAT64 OPTIONS(description="Population who completed some college or obtained associate's degree. The number of people in a geographic area over the age of 25 who obtained an associate's degree, and did not complete a more advanced degree."),
  walked_to_work FLOAT64 OPTIONS(description="Walked to Work. The number of workers age 16 years and over within a geographic area who primarily walked to work.  This would mean that of any way of getting to work, they travelled the most distance walking."),
  worked_at_home FLOAT64 OPTIONS(description="Worked at Home. The count within a geographical area of workers over the age of 16 who worked at home."),
  workers_16_and_over FLOAT64 OPTIONS(description="Workers over the Age of 16. The number of people in each geography who work. Workers include those employed at private for-profit companies, the self-employed, government workers and non-profit employees."),
  associates_degree FLOAT64 OPTIONS(description="Population Completed Associate's Degree. The number of people in a geographic area over the age of 25 who obtained a associate's degree, and did not complete a more advanced degree."),
  bachelors_degree FLOAT64 OPTIONS(description="Population Completed Bachelor's Degree. The number of people in a geographic area over the age of 25 who obtained a bachelor's degree, and did not complete a more advanced degree."),
  high_school_diploma FLOAT64 OPTIONS(description="Population Completed High School. The number of people in a geographic area over the age of 25 who completed high school, and did not complete a more advanced degree."),
  less_one_year_college FLOAT64 OPTIONS(description="Population completed less than one year of college, no degree. The number of people in a geographic area over the age of 25 who attended college for less than one year and no further."),
  masters_degree FLOAT64 OPTIONS(description="Population Completed Master's Degree. The number of people in a geographic area over the age of 25 who obtained a master's degree, but did not complete a more advanced degree."),
  one_year_more_college FLOAT64 OPTIONS(description="Population completed more than one year of college, no degree. The number of people in a geographic area over the age of 25 who attended college for more than one year but did not obtain a degree"),
  pop_25_years_over FLOAT64 OPTIONS(description="Population 25 Years and Over. The number of people in a geographic area who are over the age of 25.  This is used mostly as a denominator of educational attainment."),
  commute_35_44_mins FLOAT64 OPTIONS(description="Number of workers with a commute between 35 and 44 minutes. The number of workers in a geographic area over the age of 16 who do not work from home and commute in between 35 and 44 minutes. "),
  commute_60_more_mins FLOAT64 OPTIONS(description="Number of workers with a commute of over 60 minutes. The number of workers in a geographic area over the age of 16 who do not work from home and commute in over 60 minutes."),
  commute_less_10_mins FLOAT64 OPTIONS(description="Number of workers with less than 10 minute commute. The number of workers in a geographic area over the age of 16 who do not work from home and commute in less than 10 minutes."),
  commuters_16_over FLOAT64 OPTIONS(description="Workers age 16 and over who do not work from home. The number of workers in a geographic area over the age of 16 who do not work from home"),
  hispanic_any_race FLOAT64 OPTIONS(description="Hispanic of any race"),
  pop_5_years_over FLOAT64 OPTIONS(description="Population 5 Years and Over. The number of people in a geographic area who are over the age of 5.  This is primarily used as a denominator of measures of language spoken at home."),
  speak_only_english_at_home FLOAT64 OPTIONS(description="Speaks only English at Home. The number of people in a geographic area over age 5 who speak only English at home."),
  speak_spanish_at_home FLOAT64 OPTIONS(description="Speaks Spanish at Home. The number of people in a geographic area over age 5 who speak Spanish at home, possibly in addition to other languages."),
  speak_spanish_at_home_low_english FLOAT64 OPTIONS(description="Speaks Spanish at Home, speaks English less than \"very well\""),
  pop_15_and_over FLOAT64 OPTIONS(description="Population 15 Years and Over. The number of people in a geographic area who are over the age of 15.  This is used mostly as a denominator of marital status."),
  pop_never_married FLOAT64 OPTIONS(description="Never Married. The number of people in a geographic area who have never been married."),
  pop_now_married FLOAT64 OPTIONS(description="Currently married. The number of people in a geographic area who are currently married"),
  pop_separated FLOAT64 OPTIONS(description="Married but separated. The number of people in a geographic area who are married but separated"),
  pop_widowed FLOAT64 OPTIONS(description="Widowed. The number of people in a geographic area who are widowed"),
  pop_divorced FLOAT64 OPTIONS(description="Divorced. The number of people in a geographic area who are divorced"),
  do_date STRING
)
OPTIONS(
  labels=[("freebqcovid", "freebqcovid")]
);

CREATE TABLE `bigquery-public-data.census_bureau_acs.censustract_2018_5yr`
(
  geo_id STRING,
  do_date DATE,
  total_pop FLOAT64,
  households FLOAT64,
  male_pop FLOAT64,
  female_pop FLOAT64,
  median_age FLOAT64,
  male_under_5 FLOAT64,
  male_5_to_9 FLOAT64,
  male_10_to_14 FLOAT64,
  male_15_to_17 FLOAT64,
  male_18_to_19 FLOAT64,
  male_20 FLOAT64,
  male_21 FLOAT64,
  male_22_to_24 FLOAT64,
  male_25_to_29 FLOAT64,
  male_30_to_34 FLOAT64,
  male_35_to_39 FLOAT64,
  male_40_to_44 FLOAT64,
  male_45_to_49 FLOAT64,
  male_50_to_54 FLOAT64,
  male_55_to_59 FLOAT64,
  male_60_to_61 FLOAT64,
  male_62_to_64 FLOAT64,
  male_65_to_66 FLOAT64,
  male_67_to_69 FLOAT64,
  male_70_to_74 FLOAT64,
  male_75_to_79 FLOAT64,
  male_80_to_84 FLOAT64,
  male_85_and_over FLOAT64,
  female_under_5 FLOAT64,
  female_5_to_9 FLOAT64,
  female_10_to_14 FLOAT64,
  female_15_to_17 FLOAT64,
  female_18_to_19 FLOAT64,
  female_20 FLOAT64,
  female_21 FLOAT64,
  female_22_to_24 FLOAT64,
  female_25_to_29 FLOAT64,
  female_30_to_34 FLOAT64,
  female_35_to_39 FLOAT64,
  female_40_to_44 FLOAT64,
  female_45_to_49 FLOAT64,
  female_50_to_54 FLOAT64,
  female_55_to_59 FLOAT64,
  female_60_to_61 FLOAT64,
  female_62_to_64 FLOAT64,
  female_65_to_66 FLOAT64,
  female_67_to_69 FLOAT64,
  female_70_to_74 FLOAT64,
  female_75_to_79 FLOAT64,
  female_80_to_84 FLOAT64,
  female_85_and_over FLOAT64,
  white_pop FLOAT64,
  population_1_year_and_over FLOAT64,
  population_3_years_over FLOAT64,
  pop_5_years_over FLOAT64,
  pop_15_and_over FLOAT64,
  pop_16_over FLOAT64,
  pop_25_years_over FLOAT64,
  pop_25_64 FLOAT64,
  pop_never_married FLOAT64,
  pop_now_married FLOAT64,
  pop_separated FLOAT64,
  pop_widowed FLOAT64,
  pop_divorced FLOAT64,
  not_us_citizen_pop FLOAT64,
  black_pop FLOAT64,
  asian_pop FLOAT64,
  hispanic_pop FLOAT64,
  amerindian_pop FLOAT64,
  other_race_pop FLOAT64,
  two_or_more_races_pop FLOAT64,
  hispanic_any_race FLOAT64,
  not_hispanic_pop FLOAT64,
  asian_male_45_54 FLOAT64,
  asian_male_55_64 FLOAT64,
  black_male_45_54 FLOAT64,
  black_male_55_64 FLOAT64,
  hispanic_male_45_54 FLOAT64,
  hispanic_male_55_64 FLOAT64,
  white_male_45_54 FLOAT64,
  white_male_55_64 FLOAT64,
  median_income FLOAT64,
  income_per_capita FLOAT64,
  income_less_10000 FLOAT64,
  income_10000_14999 FLOAT64,
  income_15000_19999 FLOAT64,
  income_20000_24999 FLOAT64,
  income_25000_29999 FLOAT64,
  income_30000_34999 FLOAT64,
  income_35000_39999 FLOAT64,
  income_40000_44999 FLOAT64,
  income_45000_49999 FLOAT64,
  income_50000_59999 FLOAT64,
  income_60000_74999 FLOAT64,
  income_75000_99999 FLOAT64,
  income_100000_124999 FLOAT64,
  income_125000_149999 FLOAT64,
  income_150000_199999 FLOAT64,
  income_200000_or_more FLOAT64,
  pop_determined_poverty_status FLOAT64,
  poverty FLOAT64,
  gini_index FLOAT64,
  housing_units FLOAT64,
  renter_occupied_housing_units_paying_cash_median_gross_rent FLOAT64,
  owner_occupied_housing_units_lower_value_quartile FLOAT64,
  owner_occupied_housing_units_median_value FLOAT64,
  owner_occupied_housing_units_upper_value_quartile FLOAT64,
  occupied_housing_units FLOAT64,
  housing_units_renter_occupied FLOAT64,
  vacant_housing_units FLOAT64,
  vacant_housing_units_for_rent FLOAT64,
  vacant_housing_units_for_sale FLOAT64,
  dwellings_1_units_detached FLOAT64,
  dwellings_1_units_attached FLOAT64,
  dwellings_2_units FLOAT64,
  dwellings_3_to_4_units FLOAT64,
  dwellings_5_to_9_units FLOAT64,
  dwellings_10_to_19_units FLOAT64,
  dwellings_20_to_49_units FLOAT64,
  dwellings_50_or_more_units FLOAT64,
  mobile_homes FLOAT64,
  housing_built_2005_or_later FLOAT64,
  housing_built_2000_to_2004 FLOAT64,
  housing_built_1939_or_earlier FLOAT64,
  median_year_structure_built FLOAT64,
  married_households FLOAT64,
  nonfamily_households FLOAT64,
  family_households FLOAT64,
  households_public_asst_or_food_stamps FLOAT64,
  male_male_households FLOAT64,
  female_female_households FLOAT64,
  children FLOAT64,
  children_in_single_female_hh FLOAT64,
  median_rent FLOAT64,
  percent_income_spent_on_rent FLOAT64,
  rent_burden_not_computed FLOAT64,
  rent_over_50_percent FLOAT64,
  rent_40_to_50_percent FLOAT64,
  rent_35_to_40_percent FLOAT64,
  rent_30_to_35_percent FLOAT64,
  rent_25_to_30_percent FLOAT64,
  rent_20_to_25_percent FLOAT64,
  rent_15_to_20_percent FLOAT64,
  rent_10_to_15_percent FLOAT64,
  rent_under_10_percent FLOAT64,
  owner_occupied_housing_units FLOAT64,
  million_dollar_housing_units FLOAT64,
  mortgaged_housing_units FLOAT64,
  different_house_year_ago_different_city FLOAT64,
  different_house_year_ago_same_city FLOAT64,
  families_with_young_children FLOAT64,
  two_parent_families_with_young_children FLOAT64,
  two_parents_in_labor_force_families_with_young_children FLOAT64,
  two_parents_father_in_labor_force_families_with_young_children FLOAT64,
  two_parents_mother_in_labor_force_families_with_young_children FLOAT64,
  two_parents_not_in_labor_force_families_with_young_children FLOAT64,
  one_parent_families_with_young_children FLOAT64,
  father_one_parent_families_with_young_children FLOAT64,
  father_in_labor_force_one_parent_families_with_young_children FLOAT64,
  commute_less_10_mins FLOAT64,
  commute_10_14_mins FLOAT64,
  commute_15_19_mins FLOAT64,
  commute_20_24_mins FLOAT64,
  commute_25_29_mins FLOAT64,
  commute_30_34_mins FLOAT64,
  commute_35_44_mins FLOAT64,
  commute_60_more_mins FLOAT64,
  commute_45_59_mins FLOAT64,
  commuters_16_over FLOAT64,
  walked_to_work FLOAT64,
  worked_at_home FLOAT64,
  no_car FLOAT64,
  no_cars FLOAT64,
  one_car FLOAT64,
  two_cars FLOAT64,
  three_cars FLOAT64,
  four_more_cars FLOAT64,
  aggregate_travel_time_to_work FLOAT64,
  commuters_by_public_transportation FLOAT64,
  commuters_by_bus FLOAT64,
  commuters_by_car_truck_van FLOAT64,
  commuters_by_carpool FLOAT64,
  commuters_by_subway_or_elevated FLOAT64,
  commuters_drove_alone FLOAT64,
  group_quarters FLOAT64,
  associates_degree FLOAT64,
  bachelors_degree FLOAT64,
  high_school_diploma FLOAT64,
  less_one_year_college FLOAT64,
  masters_degree FLOAT64,
  one_year_more_college FLOAT64,
  less_than_high_school_graduate FLOAT64,
  high_school_including_ged FLOAT64,
  bachelors_degree_2 FLOAT64,
  bachelors_degree_or_higher_25_64 FLOAT64,
  graduate_professional_degree FLOAT64,
  some_college_and_associates_degree FLOAT64,
  male_45_64_associates_degree FLOAT64,
  male_45_64_bachelors_degree FLOAT64,
  male_45_64_graduate_degree FLOAT64,
  male_45_64_less_than_9_grade FLOAT64,
  male_45_64_grade_9_12 FLOAT64,
  male_45_64_high_school FLOAT64,
  male_45_64_some_college FLOAT64,
  male_45_to_64 FLOAT64,
  employed_pop FLOAT64,
  unemployed_pop FLOAT64,
  pop_in_labor_force FLOAT64,
  not_in_labor_force FLOAT64,
  workers_16_and_over FLOAT64,
  armed_forces FLOAT64,
  civilian_labor_force FLOAT64,
  employed_agriculture_forestry_fishing_hunting_mining FLOAT64,
  employed_arts_entertainment_recreation_accommodation_food FLOAT64,
  employed_construction FLOAT64,
  employed_education_health_social FLOAT64,
  employed_finance_insurance_real_estate FLOAT64,
  employed_information FLOAT64,
  employed_manufacturing FLOAT64,
  employed_other_services_not_public_admin FLOAT64,
  employed_public_administration FLOAT64,
  employed_retail_trade FLOAT64,
  employed_science_management_admin_waste FLOAT64,
  employed_transportation_warehousing_utilities FLOAT64,
  employed_wholesale_trade FLOAT64,
  occupation_management_arts FLOAT64,
  occupation_natural_resources_construction_maintenance FLOAT64,
  occupation_production_transportation_material FLOAT64,
  occupation_sales_office FLOAT64,
  occupation_services FLOAT64,
  management_business_sci_arts_employed FLOAT64,
  sales_office_employed FLOAT64,
  in_grades_1_to_4 FLOAT64,
  in_grades_5_to_8 FLOAT64,
  in_grades_9_to_12 FLOAT64,
  in_school FLOAT64,
  in_undergrad_college FLOAT64,
  speak_only_english_at_home FLOAT64,
  speak_spanish_at_home FLOAT64,
  speak_spanish_at_home_low_english FLOAT64
);
