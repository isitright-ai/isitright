-- Proposed fixture: pending owner review. How many different customers have an order.
SELECT COUNT(DISTINCT customer) AS customers FROM `my-project.shop.orders`
