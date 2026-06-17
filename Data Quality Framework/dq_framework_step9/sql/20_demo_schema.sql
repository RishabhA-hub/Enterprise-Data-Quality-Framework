-- ============================================================
-- STEP 9: END-TO-END DEMO DATASET
-- Realistic retail/finance schema with intentional data quality
-- defects so every rule, reconciliation, and quarantine path
-- exercises across the full pipeline.
-- ============================================================

CREATE SCHEMA IF NOT EXISTS demo_src;   -- "source" system (raw)
CREATE SCHEMA IF NOT EXISTS demo_tgt;   -- "target" warehouse (curated)

-- ---------- SOURCE SYSTEM (raw OLTP-like) ----------
DROP TABLE IF EXISTS demo_src.customers CASCADE;
CREATE TABLE demo_src.customers (
    customer_id      BIGINT PRIMARY KEY,
    email            TEXT,
    full_name        TEXT,
    country_code     TEXT,
    signup_date      DATE,
    status           TEXT,
    loaded_at        TIMESTAMPTZ DEFAULT now()
);

DROP TABLE IF EXISTS demo_src.products CASCADE;
CREATE TABLE demo_src.products (
    product_id       BIGINT PRIMARY KEY,
    sku              TEXT,
    name             TEXT,
    category         TEXT,
    unit_price       NUMERIC(12,2),
    active           BOOLEAN,
    loaded_at        TIMESTAMPTZ DEFAULT now()
);

DROP TABLE IF EXISTS demo_src.orders CASCADE;
CREATE TABLE demo_src.orders (
    order_id         BIGINT PRIMARY KEY,
    customer_id      BIGINT,
    order_date       TIMESTAMPTZ,
    currency         TEXT,
    total_amount     NUMERIC(14,2),
    status           TEXT,
    loaded_at        TIMESTAMPTZ DEFAULT now()
);

DROP TABLE IF EXISTS demo_src.order_items CASCADE;
CREATE TABLE demo_src.order_items (
    order_item_id    BIGINT PRIMARY KEY,
    order_id         BIGINT,
    product_id       BIGINT,
    quantity         INT,
    unit_price       NUMERIC(12,2),
    line_amount      NUMERIC(14,2),
    loaded_at        TIMESTAMPTZ DEFAULT now()
);

-- ---------- TARGET WAREHOUSE (curated) ----------
DROP TABLE IF EXISTS demo_tgt.dim_customer CASCADE;
CREATE TABLE demo_tgt.dim_customer (
    customer_id      BIGINT PRIMARY KEY,
    email            TEXT,
    full_name        TEXT,
    country_code     TEXT,
    signup_date      DATE,
    status           TEXT,
    etl_loaded_at    TIMESTAMPTZ DEFAULT now()
);

DROP TABLE IF EXISTS demo_tgt.fact_orders CASCADE;
CREATE TABLE demo_tgt.fact_orders (
    order_id         BIGINT PRIMARY KEY,
    customer_id      BIGINT,
    order_date       TIMESTAMPTZ,
    currency         TEXT,
    total_amount     NUMERIC(14,2),
    status           TEXT,
    etl_loaded_at    TIMESTAMPTZ DEFAULT now()
);

-- Grants (Data API + service role)
GRANT USAGE ON SCHEMA demo_src, demo_tgt TO authenticated, service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA demo_src TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA demo_tgt TO authenticated;
GRANT ALL ON ALL TABLES IN SCHEMA demo_src TO service_role;
GRANT ALL ON ALL TABLES IN SCHEMA demo_tgt TO service_role;
