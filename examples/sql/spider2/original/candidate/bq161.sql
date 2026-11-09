WITH paad AS (
  SELECT DISTINCT ParticipantBarcode
  FROM `isb-cgc-bq.pancancer_atlas.TCGA_CDR`
  WHERE Study = 'PAAD'
),
mut AS (
  SELECT
    ParticipantBarcode,
    LOGICAL_OR(Hugo_Symbol = 'KRAS') AS has_kras,
    LOGICAL_OR(Hugo_Symbol = 'TP53') AS has_tp53
  FROM `isb-cgc-bq.pancancer_atlas.Filtered_MC3_MAF_V5_one_per_tumor_sample`
  WHERE Study = 'PAAD'
    AND FILTER = 'PASS'
    AND Hugo_Symbol IN ('KRAS', 'TP53')
  GROUP BY ParticipantBarcode
)
SELECT
  COUNTIF(m.has_kras AND m.has_tp53) - COUNTIF(m.ParticipantBarcode IS NULL) AS net_difference
FROM paad p
LEFT JOIN mut m
  ON p.ParticipantBarcode = m.ParticipantBarcode