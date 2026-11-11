WITH t AS (
  SELECT
    tcr.OrderID AS tradeID,
    tcr.MaturityDate AS tradeTimestamp,
    CASE SUBSTR(tcr.TargetCompID, 1, 4)
      WHEN 'MOMO' THEN 'Momentum'
      WHEN 'LUCK' THEN 'Feeling Lucky'
      WHEN 'PRED' THEN 'Prediction'
    END AS algorithm,
    tcr.Symbol AS symbol,
    tcr.LastPx AS openPrice,
    tcr.StrikePrice AS closePrice,
    s.Side AS tradeDirection
  FROM `bigquery-public-data.cymbal_investments.trade_capture_report` AS tcr
  CROSS JOIN UNNEST(tcr.Sides) AS s
)
SELECT
  tradeID,
  tradeTimestamp,
  algorithm,
  symbol,
  openPrice,
  closePrice,
  tradeDirection,
  CASE tradeDirection WHEN 'SHORT' THEN -1 WHEN 'LONG' THEN 1 END AS tradeMultiplier
FROM t
ORDER BY closePrice DESC
LIMIT 6