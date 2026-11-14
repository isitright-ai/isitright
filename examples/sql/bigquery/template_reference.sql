-- Proposed fixture: pending owner review. The orders of one customer, with their line items when
-- they have any. <CUSTOMER> is a template parameter, filled with --param before parsing.
SELECT o.order_id, i.sku
FROM `my-project.shop.orders` AS o
LEFT JOIN UNNEST(o.items) AS i
WHERE o.customer = '<CUSTOMER>'
