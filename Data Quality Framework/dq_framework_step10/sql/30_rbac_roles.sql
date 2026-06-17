-- =====================================================================
-- Step 10 :: Governance, RBAC & Audit Hardening
-- File   : 30_rbac_roles.sql
-- Purpose: Create least-privilege role hierarchy for the DQ framework.
--          Roles follow Fortune-500 segregation-of-duties principles:
--            * platform_admin   - DDL, secrets, role grants (break-glass)
--            * dq_engineer      - author/modify rules + ETL recon pairs
--            * dq_operator      - execute pipelines, manage quarantine
--            * dq_steward       - triage quarantine, sign-off remediation
--            * bi_reader        - read-only on reporting.* (BI tools)
--            * app_runtime      - service account used by Airflow/Prefect
-- =====================================================================

BEGIN;

-- ---------------------------------------------------------------------
-- 1. Group roles (NOLOGIN). Humans/services inherit via GRANT ... TO.
-- ---------------------------------------------------------------------
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'platform_admin') THEN
    CREATE ROLE platform_admin NOLOGIN;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'dq_engineer') THEN
    CREATE ROLE dq_engineer NOLOGIN;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'dq_operator') THEN
    CREATE ROLE dq_operator NOLOGIN;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'dq_steward') THEN
    CREATE ROLE dq_steward NOLOGIN;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'bi_reader') THEN
    CREATE ROLE bi_reader NOLOGIN;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_runtime') THEN
    CREATE ROLE app_runtime NOLOGIN;
  END IF;
END$$;

-- ---------------------------------------------------------------------
-- 2. Schema-level privileges
-- ---------------------------------------------------------------------
GRANT USAGE ON SCHEMA dq_meta      TO dq_engineer, dq_operator, dq_steward, app_runtime;
GRANT USAGE ON SCHEMA reporting    TO bi_reader, dq_steward, app_runtime;
GRANT USAGE ON SCHEMA demo_src     TO dq_engineer, dq_operator, app_runtime;
GRANT USAGE ON SCHEMA demo_tgt     TO dq_engineer, dq_operator, app_runtime;

-- ---------------------------------------------------------------------
-- 3. Object-level privileges (least privilege)
-- ---------------------------------------------------------------------

-- dq_engineer: full CRUD on rule catalog + recon pairs; read on results
GRANT SELECT, INSERT, UPDATE, DELETE
  ON dq_meta.dq_rules,
     dq_meta.dq_etl_recon_pairs
  TO dq_engineer;

GRANT SELECT
  ON dq_meta.dq_rule_results,
     dq_meta.dq_etl_recon_results,
     dq_meta.dq_profile_results,
     dq_meta.dq_quarantine,
     dq_meta.dq_run_log
  TO dq_engineer;

-- dq_operator: execute pipelines (insert results), read catalog
GRANT SELECT ON dq_meta.dq_rules, dq_meta.dq_etl_recon_pairs TO dq_operator;
GRANT SELECT, INSERT
  ON dq_meta.dq_rule_results,
     dq_meta.dq_etl_recon_results,
     dq_meta.dq_profile_results,
     dq_meta.dq_run_log
  TO dq_operator;
GRANT SELECT, INSERT, UPDATE ON dq_meta.dq_quarantine TO dq_operator;

-- dq_steward: read everything in dq_meta, update quarantine workflow
GRANT SELECT ON ALL TABLES IN SCHEMA dq_meta TO dq_steward;
GRANT UPDATE (status, resolution_note, resolved_by, resolved_at)
  ON dq_meta.dq_quarantine TO dq_steward;
GRANT SELECT ON ALL TABLES IN SCHEMA reporting TO dq_steward;

-- bi_reader: read-only on reporting.* views ONLY (no raw tables)
GRANT SELECT ON ALL TABLES IN SCHEMA reporting TO bi_reader;
ALTER DEFAULT PRIVILEGES IN SCHEMA reporting
  GRANT SELECT ON TABLES TO bi_reader;

-- app_runtime: union of operator + read-reporting (used by schedulers)
GRANT dq_operator TO app_runtime;
GRANT SELECT ON ALL TABLES IN SCHEMA reporting TO app_runtime;

-- ---------------------------------------------------------------------
-- 4. Default privileges for FUTURE objects created by platform_admin
-- ---------------------------------------------------------------------
ALTER DEFAULT PRIVILEGES FOR ROLE platform_admin IN SCHEMA dq_meta
  GRANT SELECT ON TABLES TO dq_steward;
ALTER DEFAULT PRIVILEGES FOR ROLE platform_admin IN SCHEMA dq_meta
  GRANT SELECT, INSERT ON TABLES TO dq_operator;
ALTER DEFAULT PRIVILEGES FOR ROLE platform_admin IN SCHEMA reporting
  GRANT SELECT ON TABLES TO bi_reader, dq_steward;

-- ---------------------------------------------------------------------
-- 5. Revoke PUBLIC (defense-in-depth)
-- ---------------------------------------------------------------------
REVOKE ALL ON SCHEMA dq_meta, reporting FROM PUBLIC;
REVOKE ALL ON ALL TABLES IN SCHEMA dq_meta, reporting FROM PUBLIC;

COMMIT;
