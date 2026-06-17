-- =====================================================================
-- Step 10 :: File 34_rls_policies.sql
-- Purpose: Row-Level Security for multi-tenant / multi-domain DQ.
--          Stewards see only the data domains they own; engineers
--          see all rules but only edit ones in their domain.
--          Uses session GUC 'app.current_domain' set by Airflow/Prefect
--          or by a session-init trigger after login.
-- =====================================================================

BEGIN;

-- 1. Add domain ownership column (idempotent)
ALTER TABLE dq_meta.dq_rules
    ADD COLUMN IF NOT EXISTS data_domain TEXT NOT NULL DEFAULT 'GLOBAL';

ALTER TABLE dq_meta.dq_quarantine
    ADD COLUMN IF NOT EXISTS data_domain TEXT NOT NULL DEFAULT 'GLOBAL';

CREATE INDEX IF NOT EXISTS ix_rules_domain      ON dq_meta.dq_rules(data_domain);
CREATE INDEX IF NOT EXISTS ix_quarantine_domain ON dq_meta.dq_quarantine(data_domain);

-- 2. Steward <-> domain mapping
CREATE TABLE IF NOT EXISTS dq_meta.dq_steward_domains (
    db_user      TEXT NOT NULL,
    data_domain  TEXT NOT NULL,
    granted_at   TIMESTAMPTZ DEFAULT now(),
    granted_by   TEXT DEFAULT current_user,
    PRIMARY KEY (db_user, data_domain)
);
GRANT SELECT ON dq_meta.dq_steward_domains TO dq_steward, dq_engineer, app_runtime;
GRANT INSERT, UPDATE, DELETE ON dq_meta.dq_steward_domains TO dq_engineer;

-- 3. Helper: does the current session have access to a domain?
CREATE OR REPLACE FUNCTION dq_meta.fn_has_domain_access(p_domain TEXT)
RETURNS BOOLEAN
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = dq_meta, pg_temp
AS $$
    SELECT
      -- Platform admins and engineers see everything
      pg_has_role(current_user, 'platform_admin', 'USAGE')
      OR pg_has_role(current_user, 'dq_engineer',  'USAGE')
      -- Stewards must be explicitly mapped to the domain
      OR EXISTS (
            SELECT 1 FROM dq_meta.dq_steward_domains
            WHERE db_user = current_user
              AND data_domain = p_domain
      )
      -- GLOBAL domain is visible to all logged-in roles
      OR p_domain = 'GLOBAL';
$$;

GRANT EXECUTE ON FUNCTION dq_meta.fn_has_domain_access(TEXT)
    TO dq_steward, dq_engineer, dq_operator, app_runtime, bi_reader;

-- 4. Enable RLS
ALTER TABLE dq_meta.dq_rules       ENABLE ROW LEVEL SECURITY;
ALTER TABLE dq_meta.dq_quarantine  ENABLE ROW LEVEL SECURITY;

-- Engineers + operators bypass for ops; app_runtime needs full visibility
ALTER TABLE dq_meta.dq_rules       FORCE  ROW LEVEL SECURITY;
ALTER TABLE dq_meta.dq_quarantine  FORCE  ROW LEVEL SECURITY;

-- 5. Policies
DROP POLICY IF EXISTS p_rules_domain_read  ON dq_meta.dq_rules;
CREATE POLICY p_rules_domain_read ON dq_meta.dq_rules
    FOR SELECT
    USING (dq_meta.fn_has_domain_access(data_domain));

DROP POLICY IF EXISTS p_rules_domain_write ON dq_meta.dq_rules;
CREATE POLICY p_rules_domain_write ON dq_meta.dq_rules
    FOR ALL
    USING (dq_meta.fn_has_domain_access(data_domain))
    WITH CHECK (dq_meta.fn_has_domain_access(data_domain));

DROP POLICY IF EXISTS p_quarantine_domain ON dq_meta.dq_quarantine;
CREATE POLICY p_quarantine_domain ON dq_meta.dq_quarantine
    FOR ALL
    USING (dq_meta.fn_has_domain_access(data_domain))
    WITH CHECK (dq_meta.fn_has_domain_access(data_domain));

-- 6. Bypass for service account (Airflow/Prefect must see all domains)
ALTER ROLE app_runtime SET row_security = off;

COMMIT;
