-- =====================================================================
-- CLEAN LAYER  (Kimball star schema)
-- Only rows that pass DQ + ETL reconciliation land here.
-- Surrogate keys (BIGSERIAL) decouple the warehouse from source IDs,
-- enabling SCD handling and safe re-loads. Natural keys are preserved
-- as business keys (customer_bk, employee_bk) with UNIQUE constraints.
-- =====================================================================

DROP TABLE IF EXISTS clean.fact_sales     CASCADE;
DROP TABLE IF EXISTS clean.dim_customer   CASCADE;
DROP TABLE IF EXISTS clean.dim_employee   CASCADE;

CREATE TABLE clean.dim_customer (
    customer_sk        BIGSERIAL   PRIMARY KEY,
    customer_bk        TEXT        NOT NULL UNIQUE,        -- business key from source
    name               TEXT        NOT NULL,
    email              TEXT,
    phone              TEXT,
    state              TEXT,                                -- standardized to master list
    country            TEXT,
    income             NUMERIC(14,2) CHECK (income IS NULL OR income >= 0),
    registration_date  DATE        NOT NULL,
    effective_from     TIMESTAMPTZ NOT NULL DEFAULT now(),
    effective_to       TIMESTAMPTZ,
    is_current         BOOLEAN     NOT NULL DEFAULT TRUE
);
CREATE INDEX idx_dim_customer_bk ON clean.dim_customer(customer_bk);

CREATE TABLE clean.dim_employee (
    employee_sk    BIGSERIAL   PRIMARY KEY,
    employee_bk    TEXT        NOT NULL UNIQUE,
    age            INTEGER     CHECK (age BETWEEN 18 AND 65),
    department     TEXT        NOT NULL,
    salary         NUMERIC(14,2) CHECK (salary > 0),
    joining_date   DATE        NOT NULL CHECK (joining_date <= CURRENT_DATE),
    attrition      BOOLEAN,
    location       TEXT,
    effective_from TIMESTAMPTZ NOT NULL DEFAULT now(),
    effective_to   TIMESTAMPTZ,
    is_current     BOOLEAN     NOT NULL DEFAULT TRUE
);

CREATE TABLE clean.fact_sales (
    sales_sk        BIGSERIAL   PRIMARY KEY,
    order_bk        TEXT        NOT NULL,                    -- source order id
    customer_sk     BIGINT      NOT NULL REFERENCES clean.dim_customer(customer_sk),
    product_id      TEXT        NOT NULL,
    order_date      DATE        NOT NULL CHECK (order_date <= CURRENT_DATE),
    revenue         NUMERIC(14,2) NOT NULL CHECK (revenue > 0),
    region          TEXT,
    category        TEXT,
    load_execution_id BIGINT,                                 -- lineage back to monitoring
    UNIQUE (order_bk)
);
CREATE INDEX idx_fact_sales_customer ON clean.fact_sales(customer_sk);
CREATE INDEX idx_fact_sales_date     ON clean.fact_sales(order_date);
