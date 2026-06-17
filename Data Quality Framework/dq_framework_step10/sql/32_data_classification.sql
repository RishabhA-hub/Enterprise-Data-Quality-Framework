-- =====================================================================
-- Step 10 :: File 32_data_classification.sql
-- Purpose: Catalog of data sensitivity tags (PII / PHI / PCI / SOX /
--          Confidential / Public). Drives masking, alerting severity,
--          and BI export filtering. Aligns with NIST 800-60 and
--          ISO/IEC 27001 Annex A.8.2 (Information Classification).
-- =====================================================================

BEGIN;

CREATE TABLE IF NOT EXISTS dq_meta.dq_data_classification (
    classification_id  SERIAL PRIMARY KEY,
    schema_name        TEXT NOT NULL,
    table_name         TEXT NOT NULL,
    column_name        TEXT NOT NULL,
    sensitivity        TEXT NOT NULL
        CHECK (sensitivity IN ('PUBLIC','INTERNAL','CONFIDENTIAL',
                               'PII','PHI','PCI','SOX')),
    masking_strategy   TEXT
        CHECK (masking_strategy IN ('NONE','HASH','PARTIAL','REDACT','TOKENIZE')),
    owner_team         TEXT,
    regulatory_tag     TEXT[],   -- e.g. {'GDPR','CCPA','HIPAA'}
    notes              TEXT,
    created_at         TIMESTAMPTZ DEFAULT now(),
    updated_at         TIMESTAMPTZ DEFAULT now(),
    UNIQUE (schema_name, table_name, column_name)
);

GRANT SELECT                       ON dq_meta.dq_data_classification TO dq_steward, dq_engineer, bi_reader, app_runtime;
GRANT INSERT, UPDATE, DELETE       ON dq_meta.dq_data_classification TO dq_engineer;

-- ---------------------------------------------------------------------
-- Seed: classify the demo dataset for out-of-the-box governance demo
-- ---------------------------------------------------------------------
INSERT INTO dq_meta.dq_data_classification
    (schema_name, table_name, column_name, sensitivity, masking_strategy, owner_team, regulatory_tag, notes)
VALUES
    ('demo_src','customers','email',        'PII',          'PARTIAL',  'CRM',       ARRAY['GDPR','CCPA'], 'Primary contact identifier'),
    ('demo_src','customers','full_name',    'PII',          'PARTIAL',  'CRM',       ARRAY['GDPR'],        'Direct identifier'),
    ('demo_src','customers','phone',        'PII',          'PARTIAL',  'CRM',       ARRAY['GDPR','CCPA'], NULL),
    ('demo_src','customers','country',      'INTERNAL',     'NONE',     'CRM',       NULL,                  NULL),
    ('demo_src','orders',   'total_amount', 'SOX',          'NONE',     'Finance',   ARRAY['SOX'],         'Financial reporting'),
    ('demo_src','orders',   'currency',     'INTERNAL',     'NONE',     'Finance',   NULL,                  NULL),
    ('demo_src','products', 'unit_price',   'CONFIDENTIAL', 'NONE',     'Pricing',   NULL,                  'Competitive pricing data'),
    ('demo_tgt','fact_orders','customer_id','INTERNAL',     'HASH',     'Analytics', ARRAY['GDPR'],        'Pseudonymisation key')
ON CONFLICT (schema_name, table_name, column_name) DO NOTHING;

-- ---------------------------------------------------------------------
-- View: highlight columns lacking a classification (governance gap)
-- ---------------------------------------------------------------------
CREATE OR REPLACE VIEW reporting.v_classification_coverage AS
SELECT
    c.table_schema  AS schema_name,
    c.table_name,
    c.column_name,
    c.data_type,
    cls.sensitivity,
    cls.masking_strategy,
    CASE WHEN cls.classification_id IS NULL THEN 'UNCLASSIFIED' ELSE 'OK' END AS coverage_status
FROM information_schema.columns c
LEFT JOIN dq_meta.dq_data_classification cls
       ON cls.schema_name = c.table_schema
      AND cls.table_name  = c.table_name
      AND cls.column_name = c.column_name
WHERE c.table_schema IN ('demo_src','demo_tgt');

GRANT SELECT ON reporting.v_classification_coverage TO bi_reader, dq_steward, dq_engineer;

COMMIT;
