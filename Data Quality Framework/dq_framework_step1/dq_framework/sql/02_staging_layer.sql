-- =====================================================================
-- STAGING LAYER
-- Mirrors source files 1:1. Datatypes are deliberately permissive
-- (TEXT for emails/phones/states, NUMERIC for revenue/salary) so that
-- the profiler can capture *real* defects: bad formats, negative values,
-- future dates, duplicates, orphan keys.
-- NO primary keys, NO NOT NULL, NO foreign keys -> staging accepts everything.
-- A load_id + load_ts column ties every row to the ETL batch that loaded it.
-- =====================================================================

DROP TABLE IF EXISTS staging.stg_customer CASCADE;
CREATE TABLE staging.stg_customer (
    customer_id        TEXT,
    name               TEXT,
    email              TEXT,
    phone              TEXT,
    state              TEXT,
    country            TEXT,
    income             NUMERIC(14,2),
    registration_date  TEXT,           -- TEXT on purpose: capture bad date strings
    load_id            BIGINT      NOT NULL,
    load_ts            TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_stg_customer_load ON staging.stg_customer(load_id);

DROP TABLE IF EXISTS staging.stg_sales CASCADE;
CREATE TABLE staging.stg_sales (
    order_id       TEXT,
    customer_id    TEXT,
    product_id     TEXT,
    order_date     TEXT,
    revenue        NUMERIC(14,2),
    region         TEXT,
    category       TEXT,
    load_id        BIGINT      NOT NULL,
    load_ts        TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_stg_sales_load     ON staging.stg_sales(load_id);
CREATE INDEX idx_stg_sales_customer ON staging.stg_sales(customer_id);

DROP TABLE IF EXISTS staging.stg_employee CASCADE;
CREATE TABLE staging.stg_employee (
    employee_id    TEXT,
    age            INTEGER,
    department     TEXT,
    salary         NUMERIC(14,2),
    joining_date   TEXT,
    attrition      TEXT,
    location       TEXT,
    load_id        BIGINT      NOT NULL,
    load_ts        TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_stg_employee_load ON staging.stg_employee(load_id);
