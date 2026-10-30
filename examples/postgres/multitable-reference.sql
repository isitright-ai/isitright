SELECT c.id FROM customers c LEFT JOIN orders o ON c.id = o.customer_id;
