CREATE TABLE `bigquery-public-data.irs_990.irs_990_2012`
(
  ein STRING NOT NULL OPTIONS(description="Employer Identification Number"),
  tax_pd STRING OPTIONS(description="Tax period"),
  subseccd STRING OPTIONS(description="Subsection code"),
  unrelbusinccd STRING OPTIONS(description="Unrelated business income question"),
  initiationfees INT64 OPTIONS(description="Initiation fees amount"),
  grsrcptspublicuse INT64 OPTIONS(description="Gross receipts amount"),
  grsincmembers INT64 OPTIONS(description="Gross income from members"),
  grsincother INT64 OPTIONS(description="Gross income from other sources"),
  totcntrbgfts INT64 OPTIONS(description="Total contributions"),
  totprgmrevnue INT64 OPTIONS(description="Program service revenue"),
  invstmntinc INT64 OPTIONS(description="Investment income"),
  txexmptbndsproceeds INT64 OPTIONS(description="Tax-exempt bond proceeds"),
  royaltsinc INT64 OPTIONS(description="Royalties"),
  grsrntsreal INT64 OPTIONS(description="Gross rents -- Real estate"),
  grsrntsprsnl INT64 OPTIONS(description="Gross rents -- Personal property"),
  rntlexpnsreal INT64 OPTIONS(description="Rental expense -- Real estate"),
  rntlexpnsprsnl INT64 OPTIONS(description="Rental expense -- Personal property"),
  rntlincreal INT64 OPTIONS(description="Net rent -- Real estate"),
  rntlincprsnl INT64 OPTIONS(description="Net rent -- Personal property"),
  netrntlinc INT64 OPTIONS(description="Net rental income"),
  grsalesecur INT64 OPTIONS(description="Gross sales -- Securities"),
  grsalesothr INT64 OPTIONS(description="Gross sales -- Other assets"),
  cstbasisecur INT64 OPTIONS(description="Sales expense -- Securities"),
  cstbasisothr INT64 OPTIONS(description="Sales expense -- Other assets"),
  gnlsecur INT64 OPTIONS(description="Net gain from sales -- Securities"),
  gnlsothr INT64 OPTIONS(description="Net gain from sales -- Other assets"),
  netgnls INT64 OPTIONS(description="Sales of assets"),
  grsincfndrsng INT64 OPTIONS(description="Gross fundraising"),
  lessdirfndrsng INT64 OPTIONS(description="Fundraising expenses"),
  netincfndrsng INT64 OPTIONS(description="Fundraising income"),
  grsincgaming INT64 OPTIONS(description="Gross income from gaming"),
  lessdirgaming INT64 OPTIONS(description="Gaming expenses"),
  netincgaming INT64 OPTIONS(description="Gaming income"),
  grsalesinvent INT64 OPTIONS(description="Gross sales of inventory"),
  lesscstofgoods INT64 OPTIONS(description="Cost of goods sold (inventory)"),
  netincsales INT64 OPTIONS(description="Income from sales of inventory"),
  miscrevtot11e INT64 OPTIONS(description="Other revenue"),
  totrevenue INT64 OPTIONS(description="Total revenue"),
  compnsatncurrofcr INT64 OPTIONS(description="Compensation of current officers, directors, etc"),
  othrsalwages INT64 OPTIONS(description="Other salaries and wages"),
  payrolltx INT64 OPTIONS(description="Payroll taxes"),
  profndraising INT64 OPTIONS(description="Professional fundraising fees"),
  totfuncexpns INT64 OPTIONS(description="Total functional expenses"),
  totassetsend INT64 OPTIONS(description="Total assets -- eoy"),
  txexmptbndsend INT64 OPTIONS(description="Tax-exempt bond liabilities -- eoy"),
  secrdmrtgsend INT64 OPTIONS(description="Secured mortgages and notes payable -- eoy"),
  unsecurednotesend INT64 OPTIONS(description="Unsecured mortgages and notes payable -- eoy"),
  totliabend INT64 OPTIONS(description="Total liabilities -- eoy"),
  retainedearnend INT64 OPTIONS(description="Paid-in or capital surplus -- eoy"),
  totnetassetend INT64 OPTIONS(description="Total Net Assets -- eoy"),
  nonpfrea STRING OPTIONS(description="Reason for non-PF status"),
  gftgrntsrcvd170 INT64 OPTIONS(description="Gifts grants membership fees received (170)"),
  txrevnuelevied170 INT64 OPTIONS(description="Tax revenues levied (170)"),
  srvcsval170 INT64 OPTIONS(description="Services or facilities furnished by gov (170)"),
  grsinc170 INT64 OPTIONS(description="Gross income from interest etc (170)"),
  grsrcptsrelated170 INT64 OPTIONS(description="Gross receipts from related activities (170)"),
  totgftgrntrcvd509 INT64 OPTIONS(description="Gifts grants membership fees received (509)"),
  grsrcptsadmissn509 INT64 OPTIONS(description="Receipts from admissions merchandise etc (509)"),
  txrevnuelevied509 INT64 OPTIONS(description="Tax revenues levied (509)"),
  srvcsval509 INT64 OPTIONS(description="Services or facilities furnished by gov (509)"),
  subtotsuppinc509 INT64 OPTIONS(description="Subtotal total support (509)"),
  totsupp509 INT64 OPTIONS(description="Total support (509)")
);

CREATE TABLE `bigquery-public-data.irs_990.irs_990_2013`
(
  ein STRING NOT NULL OPTIONS(description="Employer Identification Number"),
  tax_pd INT64 OPTIONS(description="Tax period"),
  subseccd INT64 OPTIONS(description="Subsection code"),
  s501c3or4947a1cd STRING OPTIONS(description="Described in 501(c)(3)?"),
  schdbind STRING OPTIONS(description="Schedule B required?"),
  politicalactvtscd STRING OPTIONS(description="Political activities?"),
  lbbyingactvtscd STRING OPTIONS(description="Lobbying activities?"),
  subjto6033cd STRING OPTIONS(description="Subject to proxy tax?"),
  dnradvisedfundscd STRING OPTIONS(description="Donor advised funds?"),
  prptyintrcvdcd STRING OPTIONS(description="Conservation easements?"),
  maintwrkofartcd STRING OPTIONS(description="Collections of art?"),
  crcounselingqstncd STRING OPTIONS(description="Credit counseling?"),
  hldassetsintermpermcd STRING OPTIONS(description="Term or permanent endowments?"),
  rptlndbldgeqptcd STRING OPTIONS(description="Land buildings and equipment reported?"),
  rptinvstothsecd STRING OPTIONS(description="Investments in other securities reported?"),
  rptinvstprgrelcd STRING OPTIONS(description="Program related investments reported?"),
  rptothasstcd STRING OPTIONS(description="Other assets reported?"),
  rptothliabcd STRING OPTIONS(description="Other liabilities reported?"),
  sepcnsldtfinstmtcd STRING OPTIONS(description="Separate consolidated financial statement"),
  sepindaudfinstmtcd STRING OPTIONS(description="Separate audited financial statement"),
  inclinfinstmtcd STRING OPTIONS(description="Included in consolidated financial statements?"),
  operateschools170cd STRING OPTIONS(description="School?"),
  frgnofficecd STRING OPTIONS(description="Foreign office?"),
  frgnrevexpnscd STRING OPTIONS(description="Foreign activities, etc?"),
  frgngrntscd STRING OPTIONS(description="More than $5000 to organizations Part IX, line 3?"),
  frgnaggragrntscd STRING OPTIONS(description="More than $5000 to individuals Part IX, line 3?"),
  rptprofndrsngfeescd STRING OPTIONS(description="Professional fundraising?"),
  rptincfnndrsngcd STRING OPTIONS(description="Fundraising activities?"),
  rptincgamingcd STRING OPTIONS(description="Gaming?"),
  operatehosptlcd STRING OPTIONS(description="Hospital?"),
  hospaudfinstmtcd STRING OPTIONS(description="Hospital audited financial statement included?"),
  rptgrntstogovtcd STRING OPTIONS(description="Grants to organizations?"),
  rptgrntstoindvcd STRING OPTIONS(description="Grants to individuals?"),
  rptyestocompnstncd STRING OPTIONS(description="Schedule J required?"),
  txexmptbndcd STRING OPTIONS(description="Tax exempt bonds?"),
  invstproceedscd STRING OPTIONS(description="Investment income?"),
  maintescrwaccntcd STRING OPTIONS(description="Escrow account?"),
  actonbehalfcd STRING OPTIONS(description="On behalf of issuer?"),
  engageexcessbnftcd STRING OPTIONS(description="Excess benefit transaction?"),
  awarexcessbnftcd STRING OPTIONS(description="Prior excess benefit transaction?"),
  loantofficercd STRING OPTIONS(description="Loan to officer or DQP?"),
  grantoofficercd STRING OPTIONS(description="Grant to related person?"),
  dirbusnreltdcd STRING OPTIONS(description="Business relationship with organization?"),
  fmlybusnreltdcd STRING OPTIONS(description="Business relationship thru family member?"),
  servasofficercd STRING OPTIONS(description="Officer, etc. of entity with business relationship?"),
  recvnoncashcd STRING OPTIONS(description="Deductible non-cash contributions?"),
  recvartcd STRING OPTIONS(description="Deductible contributions of art, etc?"),
  ceaseoperationscd STRING OPTIONS(description="Terminated?"),
  sellorexchcd STRING OPTIONS(description="Partial liquidation?"),
  ownsepentcd STRING OPTIONS(description="Disregarded entity?"),
  reltdorgcd STRING OPTIONS(description="Related entity?"),
  intincntrlcd STRING OPTIONS(description="Related organization a controlled entity?"),
  orgtrnsfrcd STRING OPTIONS(description="Any transfers to exempt non-charitable org?"),
  conduct5percentcd STRING OPTIONS(description="Activities conducted thru partnership?"),
  compltschocd STRING OPTIONS(description="Schedule O completed?"),
  f1096cnt INT64 OPTIONS(description="Number forms transmitted with 1096"),
  fw2gcnt INT64 OPTIONS(description="Number W-2Gs included in 1a"),
  wthldngrulescd STRING OPTIONS(description="Compliance with backup witholding?"),
  noemplyeesw3cnt INT64 OPTIONS(description="Number of employees"),
  filerqrdrtnscd STRING OPTIONS(description="Employment tax returns filed?"),
  unrelbusinccd STRING OPTIONS(description="Unrelated business income?"),
  filedf990tcd STRING OPTIONS(description="Form 990-T filed?"),
  frgnacctcd STRING OPTIONS(description="Foreign financial account?"),
  prohibtdtxshltrcd STRING OPTIONS(description="Prohibited tax shelter transaction?"),
  prtynotifyorgcd STRING OPTIONS(description="Taxable party notification?"),
  filedf8886tcd STRING OPTIONS(description="Form 8886-T filed?"),
  solicitcntrbcd STRING OPTIONS(description="Non-deductible contributions?"),
  exprstmntcd STRING OPTIONS(description="Non-deduct. disclosure?"),
  providegoodscd STRING OPTIONS(description="Quid pro quo contributions?"),
  notfydnrvalcd STRING OPTIONS(description="Quid pro quo disclosure?"),
  filedf8282cd STRING OPTIONS(description="Form 8282 property disposed of?"),
  f8282cnt INT64 OPTIONS(description="Number of 8282s filed"),
  fndsrcvdcd STRING OPTIONS(description="Funds to pay premiums?"),
  premiumspaidcd STRING OPTIONS(description="Premiums paid?"),
  filedf8899cd STRING OPTIONS(description="Form 8899 filed?"),
  filedf1098ccd STRING OPTIONS(description="Form 1098-C filed?"),
  excbushldngscd STRING OPTIONS(description="Excess business holdings?"),
  s4966distribcd STRING OPTIONS(description="Taxable distributions?"),
  distribtodonorcd STRING OPTIONS(description="Distribution to donor?"),
  initiationfees INT64 OPTIONS(description="Initiation fees amount"),
  grsrcptspublicuse INT64 OPTIONS(description="Gross receipts amount"),
  grsincmembers INT64 OPTIONS(description="Gross income from members"),
  grsincother INT64 OPTIONS(description="Gross income from other sources"),
  filedlieuf1041cd STRING OPTIONS(description="Form 990 in lieu of 1041?"),
  txexmptint INT64 OPTIONS(description="Tax exempt interest in lieu of 1041"),
  qualhlthplncd STRING OPTIONS(description="Qualified health plan in multiple states"),
  qualhlthreqmntn INT64 OPTIONS(description="Qualified health plan reserves required"),
  qualhlthonhnd INT64 OPTIONS(description="Qualified health plan reserves on hand"),
  rcvdpdtngcd STRING OPTIONS(description="Payments for indoor tanning"),
  filedf720cd STRING OPTIONS(description="Filed Form 720 for tanning"),
  totreprtabled INT64 OPTIONS(description="Reportable compensation from organization"),
  totcomprelatede INT64 OPTIONS(description="Reportable compensation from related orgs"),
  totestcompf INT64 OPTIONS(description="Other compensation"),
  noindiv100kcnt INT64 OPTIONS(description="Number individuals greater than $100K"),
  nocontractor100kcnt INT64 OPTIONS(description="Number of contractors greater than $100K"),
  totcntrbgfts INT64 OPTIONS(description="Total contributions"),
  prgmservcode2acd INT64 OPTIONS(description="Program service revenue code 2a"),
  totrev2acola INT64 OPTIONS(description="Program service revenue amount 2a"),
  prgmservcode2bcd INT64 OPTIONS(description="Program service revenue code 2b"),
  totrev2bcola INT64 OPTIONS(description="Program service revenue amount 2b"),
  prgmservcode2ccd INT64 OPTIONS(description="Program service revenue code 2c"),
  totrev2ccola INT64 OPTIONS(description="Program service revenue amount 2c"),
  prgmservcode2dcd INT64 OPTIONS(description="Program service revenue code 2d"),
  totrev2dcola INT64 OPTIONS(description="Program service revenue amount 2d"),
  prgmservcode2ecd INT64 OPTIONS(description="Program service revenue code 2e"),
  totrev2ecola INT64 OPTIONS(description="Program service revenue amount 2e"),
  totrev2fcola INT64 OPTIONS(description="Program service revenue amount 2f"),
  totprgmrevnue INT64 OPTIONS(description="Program service revenue"),
  invstmntinc INT64 OPTIONS(description="Investment income"),
  txexmptbndsproceeds INT64 OPTIONS(description="Tax-exempt bond proceeds"),
  royaltsinc INT64 OPTIONS(description="Royalties"),
  grsrntsreal INT64 OPTIONS(description="Gross rents -- Real estate"),
  grsrntsprsnl INT64 OPTIONS(description="Gross rents -- Personal property"),
  rntlexpnsreal INT64 OPTIONS(description="Rental expense -- Real estate"),
  rntlexpnsprsnl INT64 OPTIONS(description="Rental expense -- Personal property"),
  rntlincreal INT64 OPTIONS(description="Net rent -- Real estate"),
  rntlincprsnl INT64 OPTIONS(description="Net rent -- Personal property"),
  netrntlinc INT64 OPTIONS(description="Net rental income"),
  grsalesecur INT64 OPTIONS(description="Gross sales -- Securities"),
  grsalesothr INT64 OPTIONS(description="Gross sales -- Other assets"),
  cstbasisecur INT64 OPTIONS(description="Sales expense -- Securities"),
  cstbasisothr INT64 OPTIONS(description="Sales expense -- Other assets"),
  gnlsecur INT64 OPTIONS(description="Net gain from sales -- Securities"),
  gnlsothr INT64 OPTIONS(description="Net gain from sales -- Other assets"),
  netgnls INT64 OPTIONS(description="Sales of assets"),
  grsincfndrsng INT64 OPTIONS(description="Gross fundraising"),
  lessdirfndrsng INT64 OPTIONS(description="Fundraising expenses"),
  netincfndrsng INT64 OPTIONS(description="Fundraising income"),
  grsincgaming INT64 OPTIONS(description="Gross income from gaming"),
  lessdirgaming INT64 OPTIONS(description="Gaming expenses"),
  netincgaming INT64 OPTIONS(description="Gaming income"),
  grsalesinvent INT64 OPTIONS(description="Gross sales of inventory"),
  lesscstofgoods INT64 OPTIONS(description="Cost of goods sold (inventory)"),
  netincsales INT64 OPTIONS(description="Income from sales of inventory"),
  miscrev11acd INT64 OPTIONS(description="Other revenue code 11a"),
  miscrevtota INT64 OPTIONS(description="Other revenue amount 11a"),
  miscrev11bcd INT64 OPTIONS(description="Other revenue code 11b"),
  miscrevtot11b INT64 OPTIONS(description="Other revenue amount 11b"),
  miscrev11ccd INT64 OPTIONS(description="Other revenue code 11c"),
  miscrevtot11c INT64 OPTIONS(description="Other revenue amount 11c"),
  miscrevtot11d INT64 OPTIONS(description="Other revenue amount 11d"),
  miscrevtot11e INT64 OPTIONS(description="Other revenue"),
  totrevenue INT64 OPTIONS(description="Total revenue"),
  grntstogovt INT64 OPTIONS(description="Grants to governments/orgs in the US"),
  grnsttoindiv INT64 OPTIONS(description="Grants to individuals in the US"),
  grntstofrgngovt INT64 OPTIONS(description="Grants to orgs and individuals outside the US"),
  benifitsmembrs INT64 OPTIONS(description="Benefits paid to or for members"),
  compnsatncurrofcr INT64 OPTIONS(description="Compensation of current officers, directors, etc"),
  compnsatnandothr INT64 OPTIONS(description="Compensation of disqualified persons"),
  othrsalwages INT64 OPTIONS(description="Other salaries and wages"),
  pensionplancontrb INT64 OPTIONS(description="Pension plan contributions"),
  othremplyeebenef INT64 OPTIONS(description="Other employee benefits"),
  payrolltx INT64 OPTIONS(description="Payroll taxes"),
  feesforsrvcmgmt INT64 OPTIONS(description="Management fees"),
  legalfees INT64 OPTIONS(description="Legal fees"),
  accntingfees INT64 OPTIONS(description="Accounting fees"),
  feesforsrvclobby INT64 OPTIONS(description="Lobbying fees"),
  profndraising INT64 OPTIONS(description="Professional fundraising fees"),
  feesforsrvcinvstmgmt INT64 OPTIONS(description="Investment management feed"),
  feesforsrvcothr INT64 OPTIONS(description="Other fees"),
  advrtpromo INT64 OPTIONS(description="Advertising and promotion"),
  officexpns INT64 OPTIONS(description="Office expenses"),
  infotech INT64 OPTIONS(description="Information technology"),
  royaltsexpns INT64 OPTIONS(description="Royalties"),
  occupancy INT64 OPTIONS(description="Occupancy"),
  travel INT64 OPTIONS(description="Travel"),
  travelofpublicoffcl INT64 OPTIONS(description="Travel/entertainment expenses to public officials"),
  converconventmtng INT64 OPTIONS(description="Conferences, conventions, meetings"),
  interestamt INT64 OPTIONS(description="Interest expense"),
  pymtoaffiliates INT64 OPTIONS(description="Payments to affiliates"),
  deprcatndepletn INT64 OPTIONS(description="Depreciation, depletion, amortization"),
  insurance INT64 OPTIONS(description="Insurance"),
  othrexpnsa INT64 OPTIONS(description="Other expenses 24a"),
  othrexpnsb INT64 OPTIONS(description="Other expenses 24b"),
  othrexpnsc INT64 OPTIONS(description="Other expenses 24c"),
  othrexpnsd INT64 OPTIONS(description="Other expenses 24d"),
  othrexpnse INT64 OPTIONS(description="Other expenses 24e"),
  othrexpnsf INT64 OPTIONS(description="Other expenses 24f"),
  totfuncexpns INT64 OPTIONS(description="Total functional expenses"),
  nonintcashend INT64 OPTIONS(description="Cash -- non-interest bearing -- eoy"),
  svngstempinvend INT64 OPTIONS(description="Savings and temporary cash investments -- eoy"),
  pldgegrntrcvblend INT64 OPTIONS(description="Pledges and grants receivable -- eoy"),
  accntsrcvblend INT64 OPTIONS(description="Accounts receivable -- eoy"),
  currfrmrcvblend INT64 OPTIONS(description="Receivables from officers, directors, etc. -- eoy"),
  rcvbldisqualend INT64 OPTIONS(description="Receivables from disqualified persons -- eoy"),
  notesloansrcvblend INT64 OPTIONS(description="Notes and loans receivables -- eoy"),
  invntriesalesend INT64 OPTIONS(description="Inventories for sale or use -- eoy"),
  prepaidexpnsend INT64 OPTIONS(description="Prepaid expenses or deferred charges -- eoy"),
  lndbldgsequipend INT64 OPTIONS(description="Land, buildings, & equipment (net) -- eoy"),
  invstmntsend INT64 OPTIONS(description="Investments in publicly traded securities -- eoy"),
  invstmntsothrend INT64 OPTIONS(description="Investments in other securities -- eoy"),
  invstmntsprgmend INT64 OPTIONS(description="Program-related investments -- eoy"),
  intangibleassetsend INT64 OPTIONS(description="Intangible assets -- eoy"),
  othrassetsend INT64 OPTIONS(description="Other assets -- eoy"),
  totassetsend INT64 OPTIONS(description="Total assets -- eoy"),
  accntspayableend INT64 OPTIONS(description="Accounts payable and accrued expenses -- eoy"),
  grntspayableend INT64 OPTIONS(description="Grants payable -- eoy"),
  deferedrevnuend INT64 OPTIONS(description="Deferred revenue -- eoy"),
  txexmptbndsend INT64 OPTIONS(description="Tax-exempt bond liabilities -- eoy"),
  escrwaccntliabend INT64 OPTIONS(description="Escrow account liability -- eoy"),
  paybletoffcrsend INT64 OPTIONS(description="Payables to officers, directors, etc. -- eoy"),
  secrdmrtgsend INT64 OPTIONS(description="Secured mortgages and notes payable -- eoy"),
  unsecurednotesend INT64 OPTIONS(description="Unsecured mortgages and notes payable -- eoy"),
  othrliabend INT64 OPTIONS(description="Other liabilities -- eoy"),
  totliabend INT64 OPTIONS(description="Total liabilities -- eoy"),
  unrstrctnetasstsend INT64 OPTIONS(description="Unrestricted net assets -- eoy"),
  temprstrctnetasstsend INT64 OPTIONS(description="Temporarily restricted net assets -- eoy"),
  permrstrctnetasstsend INT64 OPTIONS(description="Permanently restricted net assets -- eoy"),
  capitalstktrstend INT64 OPTIONS(description="Retained earnings -- eoy"),
  paidinsurplusend INT64 OPTIONS(description="Permanently restricted net assets -- eoy"),
  retainedearnend INT64 OPTIONS(description="Paid-in or capital surplus -- eoy"),
  totnetassetend INT64 OPTIONS(description="Total Net Assets -- eoy"),
  totnetliabastend INT64 OPTIONS(description="Total Liabilities + Net Assets -- eoy"),
  nonpfrea INT64 OPTIONS(description="Reason for non-PF status"),
  totnooforgscnt INT64 OPTIONS(description="Number of organizations supported"),
  totsupport INT64 OPTIONS(description="Sum of amounts of support"),
  gftgrntsrcvd170 INT64 OPTIONS(description="Gifts grants membership fees received (170)"),
  txrevnuelevied170 INT64 OPTIONS(description="Tax revenues levied (170)"),
  srvcsval170 INT64 OPTIONS(description="Services or facilities furnished by gov (170)"),
  pubsuppsubtot170 INT64 OPTIONS(description="Public support subtotal (170)"),
  exceeds2pct170 INT64 OPTIONS(description="Amount support exceeds total (170)"),
  pubsupplesspct170 INT64 OPTIONS(description="Public support (170)"),
  samepubsuppsubtot170 INT64 OPTIONS(description="Public support from line 4 (170)"),
  grsinc170 INT64 OPTIONS(description="Gross income from interest etc (170)"),
  netincunreltd170 INT64 OPTIONS(description="Net UBI (170)"),
  othrinc170 INT64 OPTIONS(description="Other income (170)"),
  totsupp170 INT64 OPTIONS(description="Total support (170)"),
  grsrcptsrelated170 INT64 OPTIONS(description="Gross receipts from related activities (170)"),
  totgftgrntrcvd509 INT64 OPTIONS(description="Gifts grants membership fees received (509)"),
  grsrcptsadmissn509 INT64 OPTIONS(description="Receipts from admissions merchandise etc (509)"),
  grsrcptsactivities509 INT64 OPTIONS(description="Gross receipts from related activities (509)"),
  txrevnuelevied509 INT64 OPTIONS(description="Tax revenues levied (509)"),
  srvcsval509 INT64 OPTIONS(description="Services or facilities furnished by gov (509)"),
  pubsuppsubtot509 INT64 OPTIONS(description="Public support subtotal (509)"),
  rcvdfrmdisqualsub509 INT64 OPTIONS(description="Amounts from disqualified persons (509)"),
  exceeds1pct509 INT64 OPTIONS(description="Amount support exceeds total (509)"),
  subtotpub509 INT64 OPTIONS(description="Public support subtotal (509)"),
  pubsupplesub509 INT64 OPTIONS(description="Public support (509)"),
  samepubsuppsubtot509 INT64 OPTIONS(description="Public support from line 6 (509)"),
  grsinc509 INT64 OPTIONS(description="Gross income from interest etc (509)"),
  unreltxincls511tx509 INT64 OPTIONS(description="Net UBI (509)"),
  subtotsuppinc509 INT64 OPTIONS(description="Subtotal total support (509)"),
  netincunrelatd509 INT64 OPTIONS(description="Net income from UBI not in 10b (509)"),
  othrinc509 INT64 OPTIONS(description="Other income (509)"),
  totsupp509 INT64 OPTIONS(description="Total support (509)")
);

CREATE TABLE `bigquery-public-data.irs_990.irs_990_2014`
(
  ein STRING NOT NULL,
  tax_pd INT64,
  subseccd INT64,
  s501c3or4947a1cd STRING,
  schdbind STRING,
  politicalactvtscd STRING,
  lbbyingactvtscd STRING,
  subjto6033cd STRING,
  dnradvisedfundscd STRING,
  prptyintrcvdcd STRING,
  maintwrkofartcd STRING,
  crcounselingqstncd STRING,
  hldassetsintermpermcd STRING,
  rptlndbldgeqptcd STRING,
  rptinvstothsecd STRING,
  rptinvstprgrelcd STRING,
  rptothasstcd STRING,
  rptothliabcd STRING,
  sepcnsldtfinstmtcd STRING,
  sepindaudfinstmtcd STRING,
  inclinfinstmtcd STRING,
  operateschools170cd STRING,
  frgnofficecd STRING,
  frgnrevexpnscd STRING,
  frgngrntscd STRING,
  frgnaggragrntscd STRING,
  rptprofndrsngfeescd STRING,
  rptincfnndrsngcd STRING,
  rptincgamingcd STRING,
  operatehosptlcd STRING,
  hospaudfinstmtcd STRING,
  rptgrntstogovtcd STRING,
  rptgrntstoindvcd STRING,
  rptyestocompnstncd STRING,
  txexmptbndcd STRING,
  invstproceedscd STRING,
  maintescrwaccntcd STRING,
  actonbehalfcd STRING,
  engageexcessbnftcd STRING,
  awarexcessbnftcd STRING,
  loantofficercd STRING,
  grantoofficercd STRING,
  dirbusnreltdcd STRING,
  fmlybusnreltdcd STRING,
  servasofficercd STRING,
  recvnoncashcd STRING,
  recvartcd STRING,
  ceaseoperationscd STRING,
  sellorexchcd STRING,
  ownsepentcd STRING,
  reltdorgcd STRING,
  intincntrlcd STRING,
  orgtrnsfrcd STRING,
  conduct5percentcd STRING,
  compltschocd STRING,
  f1096cnt INT64,
  fw2gcnt INT64,
  wthldngrulescd STRING,
  noemplyeesw3cnt INT64,
  filerqrdrtnscd STRING,
  unrelbusinccd STRING,
  filedf990tcd STRING,
  frgnacctcd STRING,
  prohibtdtxshltrcd STRING,
  prtynotifyorgcd STRING,
  filedf8886tcd STRING,
  solicitcntrbcd STRING,
  exprstmntcd STRING,
  providegoodscd STRING,
  notfydnrvalcd STRING,
  filedf8282cd STRING,
  f8282cnt INT64,
  fndsrcvdcd STRING,
  premiumspaidcd STRING,
  filedf8899cd STRING,
  filedf1098ccd STRING,
  excbushldngscd STRING,
  s4966distribcd STRING,
  distribtodonorcd STRING,
  initiationfees INT64,
  grsrcptspublicuse INT64,
  grsincmembers INT64,
  grsincother INT64,
  filedlieuf1041cd STRING,
  txexmptint INT64,
  qualhlthplncd STRING,
  qualhlthreqmntn INT64,
  qualhlthonhnd INT64,
  rcvdpdtngcd STRING,
  filedf720cd STRING,
  totreprtabled INT64,
  totcomprelatede INT64,
  totestcompf INT64,
  noindiv100kcnt INT64,
  nocontractor100kcnt INT64,
  totcntrbgfts INT64,
  prgmservcode2acd INT64,
  totrev2acola INT64,
  prgmservcode2bcd INT64,
  totrev2bcola INT64,
  prgmservcode2ccd INT64,
  totrev2ccola INT64,
  prgmservcode2dcd INT64,
  totrev2dcola INT64,
  prgmservcode2ecd INT64,
  totrev2ecola INT64,
  totrev2fcola INT64,
  totprgmrevnue INT64,
  invstmntinc INT64,
  txexmptbndsproceeds INT64,
  royaltsinc INT64,
  grsrntsreal INT64,
  grsrntsprsnl INT64,
  rntlexpnsreal INT64,
  rntlexpnsprsnl INT64,
  rntlincreal INT64,
  rntlincprsnl INT64,
  netrntlinc INT64,
  grsalesecur INT64,
  grsalesothr INT64,
  cstbasisecur INT64,
  cstbasisothr INT64,
  gnlsecur INT64,
  gnlsothr INT64,
  netgnls INT64,
  grsincfndrsng INT64,
  lessdirfndrsng INT64,
  netincfndrsng INT64,
  grsincgaming INT64,
  lessdirgaming INT64,
  netincgaming INT64,
  grsalesinvent INT64,
  lesscstofgoods INT64,
  netincsales INT64,
  miscrev11acd INT64,
  miscrevtota INT64,
  miscrev11bcd INT64,
  miscrevtot11b INT64,
  miscrev11ccd INT64,
  miscrevtot11c INT64,
  miscrevtot11d INT64,
  miscrevtot11e INT64,
  totrevenue INT64,
  grntstogovt INT64,
  grnsttoindiv INT64,
  grntstofrgngovt INT64,
  benifitsmembrs INT64,
  compnsatncurrofcr INT64,
  compnsatnandothr INT64,
  othrsalwages INT64,
  pensionplancontrb INT64,
  othremplyeebenef INT64,
  payrolltx INT64,
  feesforsrvcmgmt INT64,
  legalfees INT64,
  accntingfees INT64,
  feesforsrvclobby INT64,
  profndraising INT64,
  feesforsrvcinvstmgmt INT64,
  feesforsrvcothr INT64,
  advrtpromo INT64,
  officexpns INT64,
  infotech INT64,
  royaltsexpns INT64,
  occupancy INT64,
  travel INT64,
  travelofpublicoffcl INT64,
  converconventmtng INT64,
  interestamt INT64,
  pymtoaffiliates INT64,
  deprcatndepletn INT64,
  insurance INT64,
  othrexpnsa INT64,
  othrexpnsb INT64,
  othrexpnsc INT64,
  othrexpnsd INT64,
  othrexpnse INT64,
  othrexpnsf INT64,
  totfuncexpns INT64,
  nonintcashend INT64,
  svngstempinvend INT64,
  pldgegrntrcvblend INT64,
  accntsrcvblend INT64,
  currfrmrcvblend INT64,
  rcvbldisqualend INT64,
  notesloansrcvblend INT64,
  invntriesalesend INT64,
  prepaidexpnsend INT64,
  lndbldgsequipend INT64,
  invstmntsend INT64,
  invstmntsothrend INT64,
  invstmntsprgmend INT64,
  intangibleassetsend INT64,
  othrassetsend INT64,
  totassetsend INT64,
  accntspayableend INT64,
  grntspayableend INT64,
  deferedrevnuend INT64,
  txexmptbndsend INT64,
  escrwaccntliabend INT64,
  paybletoffcrsend INT64,
  secrdmrtgsend INT64,
  unsecurednotesend INT64,
  othrliabend INT64,
  totliabend INT64,
  unrstrctnetasstsend INT64,
  temprstrctnetasstsend INT64,
  permrstrctnetasstsend INT64,
  capitalstktrstend INT64,
  paidinsurplusend INT64,
  retainedearnend INT64,
  totnetassetend INT64,
  totnetliabastend INT64,
  nonpfrea INT64,
  totnooforgscnt INT64,
  totsupport INT64,
  gftgrntsrcvd170 INT64,
  txrevnuelevied170 INT64,
  srvcsval170 INT64,
  pubsuppsubtot170 INT64,
  exceeds2pct170 INT64,
  pubsupplesspct170 INT64,
  samepubsuppsubtot170 INT64,
  grsinc170 INT64,
  netincunreltd170 INT64,
  othrinc170 INT64,
  totsupp170 INT64,
  grsrcptsrelated170 INT64,
  totgftgrntrcvd509 INT64,
  grsrcptsadmissn509 INT64,
  grsrcptsactivities509 INT64,
  txrevnuelevied509 INT64,
  srvcsval509 INT64,
  pubsuppsubtot509 INT64,
  rcvdfrmdisqualsub509 INT64,
  exceeds1pct509 INT64,
  subtotpub509 INT64,
  pubsupplesub509 INT64,
  samepubsuppsubtot509 INT64,
  grsinc509 INT64,
  unreltxincls511tx509 INT64,
  subtotsuppinc509 INT64,
  netincunrelatd509 INT64,
  othrinc509 INT64,
  totsupp509 INT64
)
OPTIONS(
  description="IRS 990 2014 dataset"
);

CREATE TABLE `bigquery-public-data.irs_990.irs_990_2015`
(
  ein STRING NOT NULL,
  elf STRING,
  tax_pd INT64,
  subseccd INT64,
  s501c3or4947a1cd STRING,
  schdbind STRING,
  politicalactvtscd STRING,
  lbbyingactvtscd STRING,
  subjto6033cd STRING,
  dnradvisedfundscd STRING,
  prptyintrcvdcd STRING,
  maintwrkofartcd STRING,
  crcounselingqstncd STRING,
  hldassetsintermpermcd STRING,
  rptlndbldgeqptcd STRING,
  rptinvstothsecd STRING,
  rptinvstprgrelcd STRING,
  rptothasstcd STRING,
  rptothliabcd STRING,
  sepcnsldtfinstmtcd STRING,
  sepindaudfinstmtcd STRING,
  inclinfinstmtcd STRING,
  operateschools170cd STRING,
  frgnofficecd STRING,
  frgnrevexpnscd STRING,
  frgngrntscd STRING,
  frgnaggragrntscd STRING,
  rptprofndrsngfeescd STRING,
  rptincfnndrsngcd STRING,
  rptincgamingcd STRING,
  operatehosptlcd STRING,
  hospaudfinstmtcd STRING,
  rptgrntstogovtcd STRING,
  rptgrntstoindvcd STRING,
  rptyestocompnstncd STRING,
  txexmptbndcd STRING,
  invstproceedscd STRING,
  maintescrwaccntcd STRING,
  actonbehalfcd STRING,
  engageexcessbnftcd STRING,
  awarexcessbnftcd STRING,
  loantofficercd STRING,
  grantoofficercd STRING,
  dirbusnreltdcd STRING,
  fmlybusnreltdcd STRING,
  servasofficercd STRING,
  recvnoncashcd STRING,
  recvartcd STRING,
  ceaseoperationscd STRING,
  sellorexchcd STRING,
  ownsepentcd STRING,
  reltdorgcd STRING,
  intincntrlcd STRING,
  orgtrnsfrcd STRING,
  conduct5percentcd STRING,
  compltschocd STRING,
  f1096cnt INT64,
  fw2gcnt INT64,
  wthldngrulescd STRING,
  noemplyeesw3cnt INT64,
  filerqrdrtnscd STRING,
  unrelbusinccd STRING,
  filedf990tcd STRING,
  frgnacctcd STRING,
  prohibtdtxshltrcd STRING,
  prtynotifyorgcd STRING,
  filedf8886tcd STRING,
  solicitcntrbcd STRING,
  exprstmntcd STRING,
  providegoodscd STRING,
  notfydnrvalcd STRING,
  filedf8282cd STRING,
  f8282cnt INT64,
  fndsrcvdcd STRING,
  premiumspaidcd STRING,
  filedf8899cd STRING,
  filedf1098ccd STRING,
  excbushldngscd STRING,
  s4966distribcd STRING,
  distribtodonorcd STRING,
  initiationfees INT64,
  grsrcptspublicuse INT64,
  grsincmembers INT64,
  grsincother INT64,
  filedlieuf1041cd STRING,
  txexmptint INT64,
  qualhlthplncd STRING,
  qualhlthreqmntn INT64,
  qualhlthonhnd INT64,
  rcvdpdtngcd STRING,
  filedf720cd STRING,
  totreprtabled INT64,
  totcomprelatede INT64,
  totestcompf INT64,
  noindiv100kcnt INT64,
  nocontractor100kcnt INT64,
  totcntrbgfts INT64,
  prgmservcode2acd INT64,
  totrev2acola INT64,
  prgmservcode2bcd INT64,
  totrev2bcola INT64,
  prgmservcode2ccd INT64,
  totrev2ccola INT64,
  prgmservcode2dcd INT64,
  totrev2dcola INT64,
  prgmservcode2ecd INT64,
  totrev2ecola INT64,
  totrev2fcola INT64,
  totprgmrevnue INT64,
  invstmntinc INT64,
  txexmptbndsproceeds INT64,
  royaltsinc INT64,
  grsrntsreal INT64,
  grsrntsprsnl INT64,
  rntlexpnsreal INT64,
  rntlexpnsprsnl INT64,
  rntlincreal INT64,
  rntlincprsnl INT64,
  netrntlinc INT64,
  grsalesecur INT64,
  grsalesothr INT64,
  cstbasisecur INT64,
  cstbasisothr INT64,
  gnlsecur INT64,
  gnlsothr INT64,
  netgnls INT64,
  grsincfndrsng INT64,
  lessdirfndrsng INT64,
  netincfndrsng INT64,
  grsincgaming INT64,
  lessdirgaming INT64,
  netincgaming INT64,
  grsalesinvent INT64,
  lesscstofgoods INT64,
  netincsales INT64,
  miscrev11acd INT64,
  miscrevtota INT64,
  miscrev11bcd INT64,
  miscrevtot11b INT64,
  miscrev11ccd INT64,
  miscrevtot11c INT64,
  miscrevtot11d INT64,
  miscrevtot11e INT64,
  totrevenue INT64,
  grntstogovt INT64,
  grnsttoindiv INT64,
  grntstofrgngovt INT64,
  benifitsmembrs INT64,
  compnsatncurrofcr INT64,
  compnsatnandothr INT64,
  othrsalwages INT64,
  pensionplancontrb INT64,
  othremplyeebenef INT64,
  payrolltx INT64,
  feesforsrvcmgmt INT64,
  legalfees INT64,
  accntingfees INT64,
  feesforsrvclobby INT64,
  profndraising INT64,
  feesforsrvcinvstmgmt INT64,
  feesforsrvcothr INT64,
  advrtpromo INT64,
  officexpns INT64,
  infotech INT64,
  royaltsexpns INT64,
  occupancy INT64,
  travel INT64,
  travelofpublicoffcl INT64,
  converconventmtng INT64,
  interestamt INT64,
  pymtoaffiliates INT64,
  deprcatndepletn INT64,
  insurance INT64,
  othrexpnsa INT64,
  othrexpnsb INT64,
  othrexpnsc INT64,
  othrexpnsd INT64,
  othrexpnse INT64,
  othrexpnsf INT64,
  totfuncexpns INT64,
  nonintcashend INT64,
  svngstempinvend INT64,
  pldgegrntrcvblend INT64,
  accntsrcvblend INT64,
  currfrmrcvblend INT64,
  rcvbldisqualend INT64,
  notesloansrcvblend INT64,
  invntriesalesend INT64,
  prepaidexpnsend INT64,
  lndbldgsequipend INT64,
  invstmntsend INT64,
  invstmntsothrend INT64,
  invstmntsprgmend INT64,
  intangibleassetsend INT64,
  othrassetsend INT64,
  totassetsend INT64,
  accntspayableend INT64,
  grntspayableend INT64,
  deferedrevnuend INT64,
  txexmptbndsend INT64,
  escrwaccntliabend INT64,
  paybletoffcrsend INT64,
  secrdmrtgsend INT64,
  unsecurednotesend INT64,
  othrliabend INT64,
  totliabend INT64,
  unrstrctnetasstsend INT64,
  temprstrctnetasstsend INT64,
  permrstrctnetasstsend INT64,
  capitalstktrstend INT64,
  paidinsurplusend INT64,
  retainedearnend INT64,
  totnetassetend INT64,
  totnetliabastend INT64,
  nonpfrea INT64,
  totnooforgscnt INT64,
  totsupport INT64,
  gftgrntsrcvd170 INT64,
  txrevnuelevied170 INT64,
  srvcsval170 INT64,
  pubsuppsubtot170 INT64,
  exceeds2pct170 INT64,
  pubsupplesspct170 INT64,
  samepubsuppsubtot170 INT64,
  grsinc170 INT64,
  netincunreltd170 INT64,
  othrinc170 INT64,
  totsupp170 INT64,
  grsrcptsrelated170 INT64,
  totgftgrntrcvd509 INT64,
  grsrcptsadmissn509 INT64,
  grsrcptsactivities509 INT64,
  txrevnuelevied509 INT64,
  srvcsval509 INT64,
  pubsuppsubtot509 INT64,
  rcvdfrmdisqualsub509 INT64,
  exceeds1pct509 INT64,
  subtotpub509 INT64,
  pubsupplesub509 INT64,
  samepubsuppsubtot509 INT64,
  grsinc509 INT64,
  unreltxincls511tx509 INT64,
  subtotsuppinc509 INT64,
  netincunrelatd509 INT64,
  othrinc509 INT64,
  totsupp509 INT64
)
OPTIONS(
  description="IRS 990 2015 dataset"
);

CREATE TABLE `bigquery-public-data.irs_990.irs_990_2016`
(
  ein STRING NOT NULL,
  elf STRING,
  tax_pd INT64,
  subseccd INT64,
  s501c3or4947a1cd STRING,
  schdbind STRING,
  politicalactvtscd STRING,
  lbbyingactvtscd STRING,
  subjto6033cd STRING,
  dnradvisedfundscd STRING,
  prptyintrcvdcd STRING,
  maintwrkofartcd STRING,
  crcounselingqstncd STRING,
  hldassetsintermpermcd STRING,
  rptlndbldgeqptcd STRING,
  rptinvstothsecd STRING,
  rptinvstprgrelcd STRING,
  rptothasstcd STRING,
  rptothliabcd STRING,
  sepcnsldtfinstmtcd STRING,
  sepindaudfinstmtcd STRING,
  inclinfinstmtcd STRING,
  operateschools170cd STRING,
  frgnofficecd STRING,
  frgnrevexpnscd STRING,
  frgngrntscd STRING,
  frgnaggragrntscd STRING,
  rptprofndrsngfeescd STRING,
  rptincfnndrsngcd STRING,
  rptincgamingcd STRING,
  operatehosptlcd STRING,
  hospaudfinstmtcd STRING,
  rptgrntstogovtcd STRING,
  rptgrntstoindvcd STRING,
  rptyestocompnstncd STRING,
  txexmptbndcd STRING,
  invstproceedscd STRING,
  maintescrwaccntcd STRING,
  actonbehalfcd STRING,
  engageexcessbnftcd STRING,
  awarexcessbnftcd STRING,
  loantofficercd STRING,
  grantoofficercd STRING,
  dirbusnreltdcd STRING,
  fmlybusnreltdcd STRING,
  servasofficercd STRING,
  recvnoncashcd STRING,
  recvartcd STRING,
  ceaseoperationscd STRING,
  sellorexchcd STRING,
  ownsepentcd STRING,
  reltdorgcd STRING,
  intincntrlcd STRING,
  orgtrnsfrcd STRING,
  conduct5percentcd STRING,
  compltschocd STRING,
  f1096cnt INT64,
  fw2gcnt INT64,
  wthldngrulescd STRING,
  noemplyeesw3cnt INT64,
  filerqrdrtnscd STRING,
  unrelbusinccd STRING,
  filedf990tcd STRING,
  frgnacctcd STRING,
  prohibtdtxshltrcd STRING,
  prtynotifyorgcd STRING,
  filedf8886tcd STRING,
  solicitcntrbcd STRING,
  exprstmntcd STRING,
  providegoodscd STRING,
  notfydnrvalcd STRING,
  filedf8282cd STRING,
  f8282cnt INT64,
  fndsrcvdcd STRING,
  premiumspaidcd STRING,
  filedf8899cd STRING,
  filedf1098ccd STRING,
  excbushldngscd STRING,
  s4966distribcd STRING,
  distribtodonorcd STRING,
  initiationfees INT64,
  grsrcptspublicuse INT64,
  grsincmembers INT64,
  grsincother INT64,
  filedlieuf1041cd STRING,
  txexmptint INT64,
  qualhlthplncd STRING,
  qualhlthreqmntn INT64,
  qualhlthonhnd INT64,
  rcvdpdtngcd STRING,
  filedf720cd STRING,
  totreprtabled INT64,
  totcomprelatede INT64,
  totestcompf INT64,
  noindiv100kcnt INT64,
  nocontractor100kcnt INT64,
  totcntrbgfts INT64,
  prgmservcode2acd INT64,
  totrev2acola INT64,
  prgmservcode2bcd INT64,
  totrev2bcola INT64,
  prgmservcode2ccd INT64,
  totrev2ccola INT64,
  prgmservcode2dcd INT64,
  totrev2dcola INT64,
  prgmservcode2ecd INT64,
  totrev2ecola INT64,
  totrev2fcola INT64,
  totprgmrevnue INT64,
  invstmntinc INT64,
  txexmptbndsproceeds INT64,
  royaltsinc INT64,
  grsrntsreal INT64,
  grsrntsprsnl INT64,
  rntlexpnsreal INT64,
  rntlexpnsprsnl INT64,
  rntlincreal INT64,
  rntlincprsnl INT64,
  netrntlinc INT64,
  grsalesecur INT64,
  grsalesothr INT64,
  cstbasisecur INT64,
  cstbasisothr INT64,
  gnlsecur INT64,
  gnlsothr INT64,
  netgnls INT64,
  grsincfndrsng INT64,
  lessdirfndrsng INT64,
  netincfndrsng INT64,
  grsincgaming INT64,
  lessdirgaming INT64,
  netincgaming INT64,
  grsalesinvent INT64,
  lesscstofgoods INT64,
  netincsales INT64,
  miscrev11acd INT64,
  miscrevtota INT64,
  miscrev11bcd INT64,
  miscrevtot11b INT64,
  miscrev11ccd INT64,
  miscrevtot11c INT64,
  miscrevtot11d INT64,
  miscrevtot11e INT64,
  totrevenue INT64,
  grntstogovt INT64,
  grnsttoindiv INT64,
  grntstofrgngovt INT64,
  benifitsmembrs INT64,
  compnsatncurrofcr INT64,
  compnsatnandothr INT64,
  othrsalwages INT64,
  pensionplancontrb INT64,
  othremplyeebenef INT64,
  payrolltx INT64,
  feesforsrvcmgmt INT64,
  legalfees INT64,
  accntingfees INT64,
  feesforsrvclobby INT64,
  profndraising INT64,
  feesforsrvcinvstmgmt INT64,
  feesforsrvcothr INT64,
  advrtpromo INT64,
  officexpns INT64,
  infotech INT64,
  royaltsexpns INT64,
  occupancy INT64,
  travel INT64,
  travelofpublicoffcl INT64,
  converconventmtng INT64,
  interestamt INT64,
  pymtoaffiliates INT64,
  deprcatndepletn INT64,
  insurance INT64,
  othrexpnsa INT64,
  othrexpnsb INT64,
  othrexpnsc INT64,
  othrexpnsd INT64,
  othrexpnse INT64,
  othrexpnsf INT64,
  totfuncexpns INT64,
  nonintcashend INT64,
  svngstempinvend INT64,
  pldgegrntrcvblend INT64,
  accntsrcvblend INT64,
  currfrmrcvblend INT64,
  rcvbldisqualend INT64,
  notesloansrcvblend INT64,
  invntriesalesend INT64,
  prepaidexpnsend INT64,
  lndbldgsequipend INT64,
  invstmntsend INT64,
  invstmntsothrend INT64,
  invstmntsprgmend INT64,
  intangibleassetsend INT64,
  othrassetsend INT64,
  totassetsend INT64,
  accntspayableend INT64,
  grntspayableend INT64,
  deferedrevnuend INT64,
  txexmptbndsend INT64,
  escrwaccntliabend INT64,
  paybletoffcrsend INT64,
  secrdmrtgsend INT64,
  unsecurednotesend INT64,
  othrliabend INT64,
  totliabend INT64,
  unrstrctnetasstsend INT64,
  temprstrctnetasstsend INT64,
  permrstrctnetasstsend INT64,
  capitalstktrstend INT64,
  paidinsurplusend INT64,
  retainedearnend INT64,
  totnetassetend INT64,
  totnetliabastend INT64,
  nonpfrea INT64,
  totnooforgscnt INT64,
  totsupport INT64,
  gftgrntsrcvd170 INT64,
  txrevnuelevied170 INT64,
  srvcsval170 INT64,
  pubsuppsubtot170 INT64,
  exceeds2pct170 INT64,
  pubsupplesspct170 INT64,
  samepubsuppsubtot170 INT64,
  grsinc170 INT64,
  netincunreltd170 INT64,
  othrinc170 INT64,
  totsupp170 INT64,
  grsrcptsrelated170 INT64,
  totgftgrntrcvd509 INT64,
  grsrcptsadmissn509 INT64,
  grsrcptsactivities509 INT64,
  txrevnuelevied509 INT64,
  srvcsval509 INT64,
  pubsuppsubtot509 INT64,
  rcvdfrmdisqualsub509 INT64,
  exceeds1pct509 INT64,
  subtotpub509 INT64,
  pubsupplesub509 INT64,
  samepubsuppsubtot509 INT64,
  grsinc509 INT64,
  unreltxincls511tx509 INT64,
  subtotsuppinc509 INT64,
  netincunrelatd509 INT64,
  othrinc509 INT64,
  totsupp509 INT64
)
OPTIONS(
  description="IRS 990 2016 dataset"
);

CREATE TABLE `bigquery-public-data.irs_990.irs_990_2017`
(
  ein STRING NOT NULL,
  elf STRING,
  tax_pd INT64,
  subseccd INT64,
  s501c3or4947a1cd STRING,
  schdbind STRING,
  politicalactvtscd STRING,
  lbbyingactvtscd STRING,
  subjto6033cd STRING,
  dnradvisedfundscd STRING,
  prptyintrcvdcd STRING,
  maintwrkofartcd STRING,
  crcounselingqstncd STRING,
  hldassetsintermpermcd STRING,
  rptlndbldgeqptcd STRING,
  rptinvstothsecd STRING,
  rptinvstprgrelcd STRING,
  rptothasstcd STRING,
  rptothliabcd STRING,
  sepcnsldtfinstmtcd STRING,
  sepindaudfinstmtcd STRING,
  inclinfinstmtcd STRING,
  operateschools170cd STRING,
  frgnofficecd STRING,
  frgnrevexpnscd STRING,
  frgngrntscd STRING,
  frgnaggragrntscd STRING,
  rptprofndrsngfeescd STRING,
  rptincfnndrsngcd STRING,
  rptincgamingcd STRING,
  operatehosptlcd STRING,
  hospaudfinstmtcd STRING,
  rptgrntstogovtcd STRING,
  rptgrntstoindvcd STRING,
  rptyestocompnstncd STRING,
  txexmptbndcd STRING,
  invstproceedscd STRING,
  maintescrwaccntcd STRING,
  actonbehalfcd STRING,
  engageexcessbnftcd STRING,
  awarexcessbnftcd STRING,
  loantofficercd STRING,
  grantoofficercd STRING,
  dirbusnreltdcd STRING,
  fmlybusnreltdcd STRING,
  servasofficercd STRING,
  recvnoncashcd STRING,
  recvartcd STRING,
  ceaseoperationscd STRING,
  sellorexchcd STRING,
  ownsepentcd STRING,
  reltdorgcd STRING,
  intincntrlcd STRING,
  orgtrnsfrcd STRING,
  conduct5percentcd STRING,
  compltschocd STRING,
  f1096cnt INT64,
  fw2gcnt INT64,
  wthldngrulescd STRING,
  noemplyeesw3cnt INT64,
  filerqrdrtnscd STRING,
  unrelbusinccd STRING,
  filedf990tcd STRING,
  frgnacctcd STRING,
  prohibtdtxshltrcd STRING,
  prtynotifyorgcd STRING,
  filedf8886tcd STRING,
  solicitcntrbcd STRING,
  exprstmntcd STRING,
  providegoodscd STRING,
  notfydnrvalcd STRING,
  filedf8282cd STRING,
  f8282cnt INT64,
  fndsrcvdcd STRING,
  premiumspaidcd STRING,
  filedf8899cd STRING,
  filedf1098ccd STRING,
  excbushldngscd STRING,
  s4966distribcd STRING,
  distribtodonorcd STRING,
  initiationfees INT64,
  grsrcptspublicuse INT64,
  grsincmembers INT64,
  grsincother INT64,
  filedlieuf1041cd STRING,
  txexmptint INT64,
  qualhlthplncd STRING,
  qualhlthreqmntn INT64,
  qualhlthonhnd INT64,
  rcvdpdtngcd STRING,
  filedf720cd STRING,
  totreprtabled INT64,
  totcomprelatede INT64,
  totestcompf INT64,
  noindiv100kcnt INT64,
  nocontractor100kcnt INT64,
  totcntrbgfts INT64,
  prgmservcode2acd INT64,
  totrev2acola INT64,
  prgmservcode2bcd INT64,
  totrev2bcola INT64,
  prgmservcode2ccd INT64,
  totrev2ccola INT64,
  prgmservcode2dcd INT64,
  totrev2dcola INT64,
  prgmservcode2ecd INT64,
  totrev2ecola INT64,
  totrev2fcola INT64,
  totprgmrevnue INT64,
  invstmntinc INT64,
  txexmptbndsproceeds INT64,
  royaltsinc INT64,
  grsrntsreal INT64,
  grsrntsprsnl INT64,
  rntlexpnsreal INT64,
  rntlexpnsprsnl INT64,
  rntlincreal INT64,
  rntlincprsnl INT64,
  netrntlinc INT64,
  grsalesecur INT64,
  grsalesothr INT64,
  cstbasisecur INT64,
  cstbasisothr INT64,
  gnlsecur INT64,
  gnlsothr INT64,
  netgnls INT64,
  grsincfndrsng INT64,
  lessdirfndrsng INT64,
  netincfndrsng INT64,
  grsincgaming INT64,
  lessdirgaming INT64,
  netincgaming INT64,
  grsalesinvent INT64,
  lesscstofgoods INT64,
  netincsales INT64,
  miscrev11acd INT64,
  miscrevtota INT64,
  miscrev11bcd INT64,
  miscrevtot11b INT64,
  miscrev11ccd INT64,
  miscrevtot11c INT64,
  miscrevtot11d INT64,
  miscrevtot11e INT64,
  totrevenue INT64,
  grntstogovt INT64,
  grnsttoindiv INT64,
  grntstofrgngovt INT64,
  benifitsmembrs INT64,
  compnsatncurrofcr INT64,
  compnsatnandothr INT64,
  othrsalwages INT64,
  pensionplancontrb INT64,
  othremplyeebenef INT64,
  payrolltx INT64,
  feesforsrvcmgmt INT64,
  legalfees INT64,
  accntingfees INT64,
  feesforsrvclobby INT64,
  profndraising INT64,
  feesforsrvcinvstmgmt INT64,
  feesforsrvcothr INT64,
  advrtpromo INT64,
  officexpns INT64,
  infotech INT64,
  royaltsexpns INT64,
  occupancy INT64,
  travel INT64,
  travelofpublicoffcl INT64,
  converconventmtng INT64,
  interestamt INT64,
  pymtoaffiliates INT64,
  deprcatndepletn INT64,
  insurance INT64,
  othrexpnsa INT64,
  othrexpnsb INT64,
  othrexpnsc INT64,
  othrexpnsd INT64,
  othrexpnse INT64,
  othrexpnsf INT64,
  totfuncexpns INT64,
  nonintcashend INT64,
  svngstempinvend INT64,
  pldgegrntrcvblend INT64,
  accntsrcvblend INT64,
  currfrmrcvblend INT64,
  rcvbldisqualend INT64,
  notesloansrcvblend INT64,
  invntriesalesend INT64,
  prepaidexpnsend INT64,
  lndbldgsequipend INT64,
  invstmntsend INT64,
  invstmntsothrend INT64,
  invstmntsprgmend INT64,
  intangibleassetsend INT64,
  othrassetsend INT64,
  totassetsend INT64,
  accntspayableend INT64,
  grntspayableend INT64,
  deferedrevnuend INT64,
  txexmptbndsend INT64,
  escrwaccntliabend INT64,
  paybletoffcrsend INT64,
  secrdmrtgsend INT64,
  unsecurednotesend INT64,
  othrliabend INT64,
  totliabend INT64,
  unrstrctnetasstsend INT64,
  temprstrctnetasstsend INT64,
  permrstrctnetasstsend INT64,
  capitalstktrstend INT64,
  paidinsurplusend INT64,
  retainedearnend INT64,
  totnetassetend INT64,
  totnetliabastend INT64,
  nonpfrea INT64,
  totnooforgscnt INT64,
  totsupport INT64,
  gftgrntsrcvd170 INT64,
  txrevnuelevied170 INT64,
  srvcsval170 INT64,
  pubsuppsubtot170 INT64,
  exceeds2pct170 INT64,
  pubsupplesspct170 INT64,
  samepubsuppsubtot170 INT64,
  grsinc170 INT64,
  netincunreltd170 INT64,
  othrinc170 INT64,
  totsupp170 INT64,
  grsrcptsrelated170 INT64,
  totgftgrntrcvd509 INT64,
  grsrcptsadmissn509 INT64,
  grsrcptsactivities509 INT64,
  txrevnuelevied509 INT64,
  srvcsval509 INT64,
  pubsuppsubtot509 INT64,
  rcvdfrmdisqualsub509 INT64,
  exceeds1pct509 INT64,
  subtotpub509 INT64,
  pubsupplesub509 INT64,
  samepubsuppsubtot509 INT64,
  grsinc509 INT64,
  unreltxincls511tx509 INT64,
  subtotsuppinc509 INT64,
  netincunrelatd509 INT64,
  othrinc509 INT64,
  totsupp509 INT64
)
OPTIONS(
  description="IRS 990 2017 dataset"
);

CREATE TABLE `bigquery-public-data.irs_990.irs_990`
(
  ein STRING NOT NULL,
  elf STRING,
  tax_pd INT64,
  subseccd INT64,
  s501c3or4947a1cd STRING,
  schdbind STRING,
  politicalactvtscd STRING,
  lbbyingactvtscd STRING,
  subjto6033cd STRING,
  dnradvisedfundscd STRING,
  prptyintrcvdcd STRING,
  maintwrkofartcd STRING,
  crcounselingqstncd STRING,
  hldassetsintermpermcd STRING,
  rptlndbldgeqptcd STRING,
  rptinvstothsecd STRING,
  rptinvstprgrelcd STRING,
  rptothasstcd STRING,
  rptothliabcd STRING,
  sepcnsldtfinstmtcd STRING,
  sepindaudfinstmtcd STRING,
  inclinfinstmtcd STRING,
  operateschools170cd STRING,
  frgnofficecd STRING,
  frgnrevexpnscd STRING,
  frgngrntscd STRING,
  frgnaggragrntscd STRING,
  rptprofndrsngfeescd STRING,
  rptincfnndrsngcd STRING,
  rptincgamingcd STRING,
  operatehosptlcd STRING,
  hospaudfinstmtcd STRING,
  rptgrntstogovtcd STRING,
  rptgrntstoindvcd STRING,
  rptyestocompnstncd STRING,
  txexmptbndcd STRING,
  invstproceedscd STRING,
  maintescrwaccntcd STRING,
  actonbehalfcd STRING,
  engageexcessbnftcd STRING,
  awarexcessbnftcd STRING,
  loantofficercd STRING,
  grantoofficercd STRING,
  dirbusnreltdcd STRING,
  fmlybusnreltdcd STRING,
  servasofficercd STRING,
  recvnoncashcd STRING,
  recvartcd STRING,
  ceaseoperationscd STRING,
  sellorexchcd STRING,
  ownsepentcd STRING,
  reltdorgcd STRING,
  intincntrlcd STRING,
  orgtrnsfrcd STRING,
  conduct5percentcd STRING,
  compltschocd STRING,
  f1096cnt INT64,
  fw2gcnt INT64,
  wthldngrulescd STRING,
  noemplyeesw3cnt INT64,
  filerqrdrtnscd STRING,
  unrelbusinccd STRING,
  filedf990tcd STRING,
  frgnacctcd STRING,
  prohibtdtxshltrcd STRING,
  prtynotifyorgcd STRING,
  filedf8886tcd STRING,
  solicitcntrbcd STRING,
  exprstmntcd STRING,
  providegoodscd STRING,
  notfydnrvalcd STRING,
  filedf8282cd STRING,
  f8282cnt INT64,
  fndsrcvdcd STRING,
  premiumspaidcd STRING,
  filedf8899cd STRING,
  filedf1098ccd STRING,
  excbushldngscd STRING,
  s4966distribcd STRING,
  distribtodonorcd STRING,
  initiationfees INT64,
  grsrcptspublicuse INT64,
  grsincmembers INT64,
  grsincother INT64,
  filedlieuf1041cd STRING,
  txexmptint INT64,
  qualhlthplncd STRING,
  qualhlthreqmntn INT64,
  qualhlthonhnd INT64,
  rcvdpdtngcd STRING,
  filedf720cd STRING,
  totreprtabled INT64,
  totcomprelatede INT64,
  totestcompf INT64,
  noindiv100kcnt INT64,
  nocontractor100kcnt INT64,
  totcntrbgfts INT64,
  prgmservcode2acd INT64,
  totrev2acola INT64,
  prgmservcode2bcd INT64,
  totrev2bcola INT64,
  prgmservcode2ccd INT64,
  totrev2ccola INT64,
  prgmservcode2dcd INT64,
  totrev2dcola INT64,
  prgmservcode2ecd INT64,
  totrev2ecola INT64,
  totrev2fcola INT64,
  totprgmrevnue INT64,
  invstmntinc INT64,
  txexmptbndsproceeds INT64,
  royaltsinc INT64,
  grsrntsreal INT64,
  grsrntsprsnl INT64,
  rntlexpnsreal INT64,
  rntlexpnsprsnl INT64,
  rntlincreal INT64,
  rntlincprsnl INT64,
  netrntlinc INT64,
  grsalesecur INT64,
  grsalesothr INT64,
  cstbasisecur INT64,
  cstbasisothr INT64,
  gnlsecur INT64,
  gnlsothr INT64,
  netgnls INT64,
  grsincfndrsng INT64,
  lessdirfndrsng INT64,
  netincfndrsng INT64,
  grsincgaming INT64,
  lessdirgaming INT64,
  netincgaming INT64,
  grsalesinvent INT64,
  lesscstofgoods INT64,
  netincsales INT64,
  miscrev11acd INT64,
  miscrevtota INT64,
  miscrev11bcd INT64,
  miscrevtot11b INT64,
  miscrev11ccd INT64,
  miscrevtot11c INT64,
  miscrevtot11d INT64,
  miscrevtot11e INT64,
  totrevenue INT64,
  grntstogovt INT64,
  grnsttoindiv INT64,
  grntstofrgngovt INT64,
  benifitsmembrs INT64,
  compnsatncurrofcr INT64,
  compnsatnandothr INT64,
  othrsalwages INT64,
  pensionplancontrb INT64,
  othremplyeebenef INT64,
  payrolltx INT64,
  feesforsrvcmgmt INT64,
  legalfees INT64,
  accntingfees INT64,
  feesforsrvclobby INT64,
  profndraising INT64,
  feesforsrvcinvstmgmt INT64,
  feesforsrvcothr INT64,
  advrtpromo INT64,
  officexpns INT64,
  infotech INT64,
  royaltsexpns INT64,
  occupancy INT64,
  travel INT64,
  travelofpublicoffcl INT64,
  converconventmtng INT64,
  interestamt INT64,
  pymtoaffiliates INT64,
  deprcatndepletn INT64,
  insurance INT64,
  othrexpnsa INT64,
  othrexpnsb INT64,
  othrexpnsc INT64,
  othrexpnsd INT64,
  othrexpnse INT64,
  othrexpnsf INT64,
  totfuncexpns INT64,
  nonintcashend INT64,
  svngstempinvend INT64,
  pldgegrntrcvblend INT64,
  accntsrcvblend INT64,
  currfrmrcvblend INT64,
  rcvbldisqualend INT64,
  notesloansrcvblend INT64,
  invntriesalesend INT64,
  prepaidexpnsend INT64,
  lndbldgsequipend INT64,
  invstmntsend INT64,
  invstmntsothrend INT64,
  invstmntsprgmend INT64,
  intangibleassetsend INT64,
  othrassetsend INT64,
  totassetsend INT64,
  accntspayableend INT64,
  grntspayableend INT64,
  deferedrevnuend INT64,
  txexmptbndsend INT64,
  escrwaccntliabend INT64,
  paybletoffcrsend INT64,
  secrdmrtgsend INT64,
  unsecurednotesend INT64,
  othrliabend INT64,
  totliabend INT64,
  unrstrctnetasstsend INT64,
  temprstrctnetasstsend INT64,
  permrstrctnetasstsend INT64,
  capitalstktrstend INT64,
  paidinsurplusend INT64,
  retainedearnend INT64,
  totnetassetend INT64,
  totnetliabastend INT64,
  nonpfrea INT64,
  totnooforgscnt INT64,
  totsupport INT64,
  gftgrntsrcvd170 INT64,
  txrevnuelevied170 INT64,
  srvcsval170 INT64,
  pubsuppsubtot170 INT64,
  exceeds2pct170 INT64,
  pubsupplesspct170 INT64,
  samepubsuppsubtot170 INT64,
  grsinc170 INT64,
  netincunreltd170 INT64,
  othrinc170 INT64,
  totsupp170 INT64,
  grsrcptsrelated170 INT64,
  totgftgrntrcvd509 INT64,
  grsrcptsadmissn509 INT64,
  grsrcptsactivities509 INT64,
  txrevnuelevied509 INT64,
  srvcsval509 INT64,
  pubsuppsubtot509 INT64,
  rcvdfrmdisqualsub509 INT64,
  exceeds1pct509 INT64,
  subtotpub509 INT64,
  pubsupplesub509 INT64,
  samepubsuppsubtot509 INT64,
  grsinc509 INT64,
  unreltxincls511tx509 INT64,
  subtotsuppinc509 INT64,
  netincunrelatd509 INT64,
  othrinc509 INT64,
  totsupp509 INT64
)
OPTIONS(
  description="IRS 990 2017 dataset"
);
