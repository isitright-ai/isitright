-- Proposed fixture: pending owner review. The same with CROSS JOIN UNNEST, which drops an order
-- whose array is empty.
SELECT o.order_id, i.sku
FROM `my-project.shop.orders` AS o
CROSS JOIN UNNEST(o.items) AS i
WHERE o.customer = '<CUSTOMER>'
