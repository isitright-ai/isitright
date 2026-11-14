-- Proposed fixture: pending owner review. Counts orders that name a customer: the same as the
-- reference only while no customer has two orders.
SELECT COUNT(customer) AS customers FROM `my-project.shop.orders`
