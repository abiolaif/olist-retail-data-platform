-- ============================================================================
-- EAS 550 Phase 1: Olist Brazilian E-Commerce Normalized Schema (3NF)
-- ============================================================================

BEGIN;

-- Drop tables in reverse dependency order for clean initialization
DROP TABLE IF EXISTS order_items CASCADE;
DROP TABLE IF EXISTS orders CASCADE;
DROP TABLE IF EXISTS products CASCADE;
DROP TABLE IF EXISTS sellers CASCADE;
DROP TABLE IF EXISTS customers CASCADE;
DROP TABLE IF EXISTS customer_accounts CASCADE;
DROP TABLE IF EXISTS locations CASCADE;

-- 1. Locations (Resolves transitive FD: zip_code_prefix -> city, state)
CREATE TABLE locations (
    zip_code_prefix CHAR(5) PRIMARY KEY,
    city            VARCHAR(100) NOT NULL,
    state           CHAR(2) NOT NULL,
    CONSTRAINT chk_zip_digits CHECK (zip_code_prefix ~ '^[0-9]{5}$'),
    CONSTRAINT chk_state_upper CHECK (state ~ '^[A-Z]{2}$')
);

-- 2. Customer Accounts (Distinct human buyers across repeat orders)
CREATE TABLE customer_accounts (
    customer_unique_id VARCHAR(32) PRIMARY KEY
);

-- 3. Customers (Order-level customer tokens mapped to account & location)
CREATE TABLE customers (
    customer_id        VARCHAR(32) PRIMARY KEY,
    customer_unique_id VARCHAR(32) NOT NULL REFERENCES customer_accounts(customer_unique_id),
    zip_code_prefix    CHAR(5) NOT NULL REFERENCES locations(zip_code_prefix)
);

-- 4. Sellers (Merchants fulfilling order items)
CREATE TABLE sellers (
    seller_id       VARCHAR(32) PRIMARY KEY,
    zip_code_prefix CHAR(5) NOT NULL REFERENCES locations(zip_code_prefix)
);

-- 5. Products (Catalog items; nullable dimensions reflect valid Olist gaps)
CREATE TABLE products (
    product_id                 VARCHAR(32) PRIMARY KEY,
    product_category_name      VARCHAR(100) NOT NULL DEFAULT 'uncategorized',
    product_name_length        INTEGER CHECK (product_name_length >= 0),
    product_description_length INTEGER CHECK (product_description_length >= 0),
    product_photos_qty         INTEGER CHECK (product_photos_qty >= 0),
    product_weight_g           INTEGER CHECK (product_weight_g >= 0),
    product_length_cm          INTEGER CHECK (product_length_cm >= 0),
    product_height_cm          INTEGER CHECK (product_height_cm >= 0),
    product_width_cm           INTEGER CHECK (product_width_cm >= 0)
);

-- 6. Orders (Header table; timestamps after purchase are NULL for unshipped/canceled orders)
CREATE TABLE orders (
    order_id                      VARCHAR(32) PRIMARY KEY,
    customer_id                   VARCHAR(32) NOT NULL UNIQUE REFERENCES customers(customer_id),
    order_status                  VARCHAR(20) NOT NULL,
    order_purchase_timestamp      TIMESTAMP NOT NULL,
    order_approved_at             TIMESTAMP NULL,
    order_delivered_carrier_date  TIMESTAMP NULL,
    order_delivered_customer_date TIMESTAMP NULL,
    order_estimated_delivery_date TIMESTAMP NOT NULL,
    CONSTRAINT chk_order_status CHECK (
        order_status IN (
            'created', 'approved', 'invoiced', 'processing',
            'shipped', 'delivered', 'unavailable', 'canceled'
        )
    )
);

-- 7. Order Items (Composite PK: order_id + order_item_id; resolves M:N between Orders, Products, Sellers)
CREATE TABLE order_items (
    order_id            VARCHAR(32) NOT NULL REFERENCES orders(order_id) ON DELETE CASCADE,
    order_item_id       INTEGER NOT NULL CHECK (order_item_id >= 1),
    product_id          VARCHAR(32) NOT NULL REFERENCES products(product_id),
    seller_id           VARCHAR(32) NOT NULL REFERENCES sellers(seller_id),
    shipping_limit_date TIMESTAMP NOT NULL,
    price               NUMERIC(10, 2) NOT NULL CHECK (price >= 0),
    freight_value       NUMERIC(10, 2) NOT NULL CHECK (freight_value >= 0),
    PRIMARY KEY (order_id, order_item_id)
);

-- Indexes on foreign keys and common analytical filter columns
CREATE INDEX idx_customers_unique_id ON customers(customer_unique_id);
CREATE INDEX idx_customers_zip ON customers(zip_code_prefix);
CREATE INDEX idx_sellers_zip ON sellers(zip_code_prefix);
CREATE INDEX idx_orders_purchase_ts ON orders(order_purchase_timestamp);
CREATE INDEX idx_order_items_product_id ON order_items(product_id);
CREATE INDEX idx_order_items_seller_id ON order_items(seller_id);

COMMIT;