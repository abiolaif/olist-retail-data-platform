-- 1. Table Row Counts
SELECT 'locations' AS table_name, COUNT(*) AS row_count FROM locations
UNION ALL SELECT 'customer_accounts', COUNT(*) FROM customer_accounts
UNION ALL SELECT 'customers', COUNT(*) FROM customers
UNION ALL SELECT 'sellers', COUNT(*) FROM sellers
UNION ALL SELECT 'products', COUNT(*) FROM products
UNION ALL SELECT 'orders', COUNT(*) FROM orders
UNION ALL SELECT 'order_items', COUNT(*) FROM order_items
ORDER BY table_name;

-- 2. Duplicate Key Checks (Must all return 0)
SELECT 'dup_orders' AS check_name, COUNT(*) AS violations FROM (
    SELECT order_id FROM orders GROUP BY order_id HAVING COUNT(*) > 1
) t
UNION ALL
SELECT 'dup_order_items', COUNT(*) FROM (
    SELECT order_id, order_item_id FROM order_items GROUP BY order_id, order_item_id HAVING COUNT(*) > 1
) t
UNION ALL
SELECT 'dup_customers', COUNT(*) FROM (
    SELECT customer_id FROM customers GROUP BY customer_id HAVING COUNT(*) > 1
) t;

-- 3. Referential Integrity Checks (Orphan checks; must all return 0)
SELECT 'orphan_order_customers' AS check_name, COUNT(*) AS violations
FROM orders o LEFT JOIN customers c ON o.customer_id = c.customer_id WHERE c.customer_id IS NULL
UNION ALL
SELECT 'orphan_item_orders', COUNT(*)
FROM order_items oi LEFT JOIN orders o ON oi.order_id = o.order_id WHERE o.order_id IS NULL
UNION ALL
SELECT 'orphan_item_products', COUNT(*)
FROM order_items oi LEFT JOIN products p ON oi.product_id = p.product_id WHERE p.product_id IS NULL
UNION ALL
SELECT 'orphan_item_sellers', COUNT(*)
FROM order_items oi LEFT JOIN sellers s ON oi.seller_id = s.seller_id WHERE s.seller_id IS NULL;

-- 4. Domain-Quality & Measure Checksums (Detects silent data drift across reruns)
SELECT
    COUNT(*) AS total_line_items,
    COUNT(DISTINCT order_id) AS distinct_orders_with_items,
    ROUND(SUM(price), 2) AS total_gmv_price,
    ROUND(SUM(freight_value), 2) AS total_freight,
    MIN(price) AS min_price,
    MAX(price) AS max_price,
    COUNT(*) FILTER (WHERE price < 0 OR freight_value < 0) AS negative_value_violations
FROM order_items;

-- 5. Domain-Quality Check: Sequential Item Numbering (1..N per order without gaps)
SELECT COUNT(*) AS orders_with_item_sequence_gaps
FROM (
    SELECT order_id, COUNT(*) AS item_cnt, MAX(order_item_id) AS max_seq
    FROM order_items
    GROUP BY order_id
    HAVING COUNT(*) <> MAX(order_item_id)
) g;