-- =====================================================================
-- Enterprise Data Quality Monitoring & ETL Validation Framework
-- Step 1: Database Design - Schema Creation
-- Target: PostgreSQL 13+
-- =====================================================================
-- Design pattern: 3-layer architecture
--   staging    -> raw ingested data (as-is from source, allows nulls/dupes)
--   monitoring -> DQ run logs, rule results, scores, ETL reconciliation
--   clean      -> conformed dimensional model (Kimball star schema)
-- Separating layers lets us measure quality BEFORE cleansing and prove
-- lineage / improvement after cleansing.
-- =====================================================================

CREATE SCHEMA IF NOT EXISTS staging;
CREATE SCHEMA IF NOT EXISTS monitoring;
CREATE SCHEMA IF NOT EXISTS clean;

COMMENT ON SCHEMA staging    IS 'Raw landed data from source systems. No constraints enforced so DQ engine can observe real defects.';
COMMENT ON SCHEMA monitoring IS 'DQ execution logs, rule results, dimension scores, ETL reconciliation results.';
COMMENT ON SCHEMA clean      IS 'Conformed star schema (dims + facts) populated only with records that pass DQ + reconciliation.';
