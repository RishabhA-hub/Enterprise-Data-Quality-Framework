-- =====================================================================
-- Step 10 :: File 31_audit_log.sql
-- Purpose: Append-only audit trail for governance events.
--          Captures WHO did WHAT to WHICH object WHEN, plus before/after.
--          Designed to satisfy SOX / GDPR / HIPAA / BCBS-239 audit asks.
-- =====================================================================

BEGIN;

CREATE TABLE IF NOT EXISTS dq_meta.dq_audit_log (
    audit_id       BIGSERIAL PRIMARY KEY,
    event_time     TIMESTAMPTZ NOT NULL DEFAULT now(),
    db_user        TEXT        NOT NULL DEFAULT current_user,
    session_user_  TEXT        NOT NULL DEFAULT session_user,
    client_addr    INET,
    application    TEXT,
    action         TEXT        NOT NULL CHECK (action IN ('INSERT','UPDATE','DELETE')),
    schema_name    TEXT        NOT NULL,
    table_name     TEXT        NOT NULL,
    row_pk         TEXT,
    old_row        JSONB,
    new_row        JSONB,
    changed_cols   TEXT[]
);

CREATE INDEX IF NOT EXISTS ix_audit_time   ON dq_meta.dq_audit_log(event_time DESC);
CREATE INDEX IF NOT EXISTS ix_audit_object ON dq_meta.dq_audit_log(schema_name, table_name);
CREATE INDEX IF NOT EXISTS ix_audit_user   ON dq_meta.dq_audit_log(db_user);

-- Append-only: revoke UPDATE/DELETE from everyone except platform_admin
REVOKE UPDATE, DELETE ON dq_meta.dq_audit_log FROM PUBLIC;
GRANT  SELECT ON dq_meta.dq_audit_log TO dq_steward, dq_engineer;
GRANT  INSERT ON dq_meta.dq_audit_log TO dq_operator, dq_engineer, dq_steward, app_runtime;

-- ---------------------------------------------------------------------
-- Generic trigger function: logs row-level changes to dq_audit_log
-- ---------------------------------------------------------------------
CREATE OR REPLACE FUNCTION dq_meta.fn_audit_trigger()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = dq_meta, pg_temp
AS $$
DECLARE
    v_pk     TEXT;
    v_old    JSONB := NULL;
    v_new    JSONB := NULL;
    v_diff   TEXT[] := ARRAY[]::TEXT[];
    k        TEXT;
BEGIN
    IF TG_OP = 'DELETE' THEN
        v_old := to_jsonb(OLD);
        v_pk  := COALESCE(v_old->>'rule_id', v_old->>'pair_id',
                          v_old->>'quarantine_id', v_old->>'id');
    ELSIF TG_OP = 'INSERT' THEN
        v_new := to_jsonb(NEW);
        v_pk  := COALESCE(v_new->>'rule_id', v_new->>'pair_id',
                          v_new->>'quarantine_id', v_new->>'id');
    ELSE  -- UPDATE
        v_old := to_jsonb(OLD);
        v_new := to_jsonb(NEW);
        v_pk  := COALESCE(v_new->>'rule_id', v_new->>'pair_id',
                          v_new->>'quarantine_id', v_new->>'id');
        FOR k IN SELECT jsonb_object_keys(v_new) LOOP
            IF (v_new->k) IS DISTINCT FROM (v_old->k) THEN
                v_diff := array_append(v_diff, k);
            END IF;
        END LOOP;
    END IF;

    INSERT INTO dq_meta.dq_audit_log(
        client_addr, application, action,
        schema_name, table_name, row_pk,
        old_row, new_row, changed_cols
    )
    VALUES (
        inet_client_addr(),
        current_setting('application_name', true),
        TG_OP, TG_TABLE_SCHEMA, TG_TABLE_NAME, v_pk,
        v_old, v_new, NULLIF(v_diff, ARRAY[]::TEXT[])
    );

    RETURN COALESCE(NEW, OLD);
END;
$$;

-- ---------------------------------------------------------------------
-- Attach triggers to governance-critical tables
-- ---------------------------------------------------------------------
DO $$
DECLARE t TEXT;
BEGIN
    FOREACH t IN ARRAY ARRAY[
        'dq_rules',
        'dq_etl_recon_pairs',
        'dq_quarantine'
    ]
    LOOP
        EXECUTE format('DROP TRIGGER IF EXISTS trg_audit_%1$s ON dq_meta.%1$s', t);
        EXECUTE format($f$
            CREATE TRIGGER trg_audit_%1$s
            AFTER INSERT OR UPDATE OR DELETE ON dq_meta.%1$s
            FOR EACH ROW EXECUTE FUNCTION dq_meta.fn_audit_trigger()
        $f$, t);
    END LOOP;
END$$;

COMMIT;
