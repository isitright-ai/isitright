-- Proposed fixture: pending owner review. Written as a candidate might: the same on any order
-- that has items, different on an order whose array is empty.
SELECT o.order_id, i.sku
FROM `my-project.shop.orders` AS o
CROSS JOIN UNNEST(o.items) AS i
