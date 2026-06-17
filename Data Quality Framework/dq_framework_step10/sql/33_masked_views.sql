-- =====================================================================
-- Step 10 :: File 33_masked_views.sql
-- Purpose: Provide BI-safe, masked views over PII/PHI/SOX columns.
--          bi_reader and downstream BI tools query ONLY these views
--          --- they have no SELECT on raw tables.
--          Masking strategies:
--            * PARTIAL : keep first 2 + last 2 chars, mask middle
--            * HASH    : SHA-256 deterministic pseudonym (no salt -> joinable)
--            * REDACT  : replace with '***REDACTED***'
-- =====================================================================

BEGIN;

CREATE SCHEMA IF NOT EXISTS reporting_masked;
GRANT USAGE ON SCHEMA reporting_masked TO bi_reader, dq_steward, app_runtime;

-- ---------------------------------------------------------------------
-- Reusable masking helpers (IMMUTABLE for index-friendliness)
-- ---------------------------------------------------------------------
CREATE OR REPLACE FUNCTION dq_meta.fn_mask_partial(p_value TEXT)
RETURNS TEXT LANGUAGE sql IMMUTABLE AS $$
    SELECT CASE
        WHEN p_value IS NULL OR length(p_value) < 4 THEN '****'
        ELSE substr(p_value,1,2) || repeat('*', greatest(length(p_value)-4,1)) || substr(p_value, length(p_value)-1)
    END
$$;

CREATE OR REPLACE FUNCTION dq_meta.fn_mask_email(p_email TEXT)
RETURNS TEXT LANGUAGE sql IMMUTABLE AS $$
    SELECT CASE
        WHEN p_email IS NULL OR position('@' IN p_email) = 0 THEN '****'
        ELSE substr(split_part(p_email,'@',1),1,1) || '***@' || split_part(p_email,'@',2)
    END
$$;

CREATE OR REPLACE FUNCTION dq_meta.fn_hash_id(p_value TEXT)
RETURNS TEXT LANGUAGE sql IMMUTABLE AS $$
    SELECT encode(digest(coalesce(p_value,''), 'sha256'), 'hex')
$$;
-- Requires pgcrypto; safe no-op if already installed.
CREATE EXTENSION IF NOT EXISTS pgcrypto;

GRANT EXECUTE ON FUNCTION dq_meta.fn_mask_partial(TEXT),
                          dq_meta.fn_mask_email(TEXT),
                          dq_meta.fn_hash_id(TEXT)
    TO bi_reader, dq_steward, app_runtime, dq_engineer;

-- ---------------------------------------------------------------------
-- Masked customer view (drop-in replacement for demo_src.customers)
-- ---------------------------------------------------------------------
CREATE OR REPLACE VIEW reporting_masked.customers AS
SELECT
    customer_id,
    dq_meta.fn_mask_partial(full_name)  AS full_name_masked,
    dq_meta.fn_mask_email(email)        AS email_masked,
    dq_meta.fn_mask_partial(phone)      AS phone_masked,
    country,
    created_at
FROM demo_src.customers;

-- ---------------------------------------------------------------------
-- Masked fact_orders (hash customer_id for pseudonymous analytics)
-- ---------------------------------------------------------------------
CREATE OR REPLACE VIEW reporting_masked.fact_orders AS
SELECT
    order_id,
    dq_meta.fn_hash_id(customer_id::text) AS customer_hash,
    product_id,
    order_date,
    quantity,
    total_amount,
    currency
FROM demo_tgt.fact_orders;

GRANT SELECT ON ALL TABLES IN SCHEMA reporting_masked TO bi_reader, dq_steward, app_runtime;
ALTER DEFAULT PRIVILEGES IN SCHEMA reporting_masked
    GRANT SELECT ON TABLES TO bi_reader, dq_steward;

COMMIT;
