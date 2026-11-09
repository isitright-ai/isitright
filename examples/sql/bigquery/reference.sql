-- Proposed fixture: pending owner review. Every order, with its line items when it has any.
SELECT o.order_id, i.sku
FROM `my-project.shop.orders` AS o
LEFT JOIN UNNEST(o.items) AS i
