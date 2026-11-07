-- Proposed fixture: pending owner review (constructed schema, written by Claude).
-- As INFORMATION_SCHEMA.TABLES.ddl returns it: a qualified name, a nested column, no key.
CREATE TABLE `my-project.shop.orders`
(
  order_id INT64 NOT NULL OPTIONS(description="Order identifier"),
  customer STRING,
  items ARRAY<STRUCT<sku STRING, qty INT64>>
);
