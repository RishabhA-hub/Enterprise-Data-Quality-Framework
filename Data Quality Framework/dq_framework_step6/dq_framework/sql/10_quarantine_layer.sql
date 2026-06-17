-- ---------------------------------------------------------------------------
-- Step 6: Quarantine schema + remediation workflow
-- ---------------------------------------------------------------------------

CREATE SCHEMA IF NOT EXISTS quarantine;

-- One generic quarantine table — payload kept as JSONB so any source table
-- can be quarantined without DDL changes. Bad row = one JSONB doc + reason.
CREATE TABLE IF NOT EXISTS quarantine.q_bad_rows (
    quarantine_id    BIGSERIAL PRIMARY KEY,
    execution_id     BIGINT NOT NULL
        REFERENCES monitoring.dq_execution_log(execution_id) ON DELETE CASCADE,
    rule_id          INT
        REFERENCES monitoring.dq_rules(rule_id),
    rule_code        TEXT,
    schema_name      TEXT NOT NULL,
    table_name       TEXT NOT NULL,
    business_key     TEXT,                 -- e.g. customer_id / order_id (text)
    payload          JSONB NOT NULL,       -- full row snapshot
    failure_reason   TEXT NOT NULL,
    severity         TEXT NOT NULL
        CHECK (severity IN ('LOW','MEDIUM','HIGH','CRITICAL')),
    status           TEXT NOT NULL DEFAULT 'OPEN'
        CHECK (status IN ('OPEN','IN_REVIEW','FIXED','REPROCESSED',
                          'IGNORED','REJECTED')),
    assigned_to      TEXT,
    quarantined_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    resolved_at      TIMESTAMPTZ,
    resolution_note  TEXT
);

CREATE INDEX IF NOT EXISTS ix_qbr_exec     ON quarantine.q_bad_rows (execution_id);
CREATE INDEX IF NOT EXISTS ix_qbr_table    ON quarantine.q_bad_rows (schema_name, table_name);
CREATE INDEX IF NOT EXISTS ix_qbr_status   ON quarantine.q_bad_rows (status);
CREATE INDEX IF NOT EXISTS ix_qbr_severity ON quarantine.q_bad_rows (severity);
CREATE INDEX IF NOT EXISTS ix_qbr_bk       ON quarantine.q_bad_rows (business_key);
CREATE INDEX IF NOT EXISTS ix_qbr_payload  ON quarantine.q_bad_rows USING GIN (payload);


-- Remediation audit trail — every status change recorded
CREATE TABLE IF NOT EXISTS quarantine.q_remediation_log (
    log_id          BIGSERIAL PRIMARY KEY,
    quarantine_id   BIGINT NOT NULL
        REFERENCES quarantine.q_bad_rows(quarantine_id) ON DELETE CASCADE,
    action          TEXT NOT NULL,        -- ASSIGNED / FIXED / REPROCESSED / IGNORED ...
    actor           TEXT NOT NULL,        -- user / system id
    note            TEXT,
    old_status      TEXT,
    new_status      TEXT,
    acted_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_qrl_qid ON quarantine.q_remediation_log (quarantine_id);


-- Auto-log status transitions via trigger
CREATE OR REPLACE FUNCTION quarantine.fn_log_status_change()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'UPDATE' AND NEW.status <> OLD.status THEN
        INSERT INTO quarantine.q_remediation_log
            (quarantine_id, action, actor, note, old_status, new_status)
        VALUES
            (NEW.quarantine_id,
             'STATUS_CHANGE',
             COALESCE(NEW.assigned_to, current_user),
             NEW.resolution_note,
             OLD.status, NEW.status);
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_qbr_status_change ON quarantine.q_bad_rows;
CREATE TRIGGER trg_qbr_status_change
AFTER UPDATE ON quarantine.q_bad_rows
FOR EACH ROW EXECUTE FUNCTION quarantine.fn_log_status_change();


-- BI views ------------------------------------------------------------------
CREATE OR REPLACE VIEW quarantine.v_open_by_table AS
SELECT schema_name, table_name, severity,
       COUNT(*)                          AS open_count,
       MIN(quarantined_at)               AS oldest_open,
       MAX(quarantined_at)               AS newest_open
  FROM quarantine.q_bad_rows
 WHERE status IN ('OPEN','IN_REVIEW')
 GROUP BY schema_name, table_name, severity;

CREATE OR REPLACE VIEW quarantine.v_sla_breaches AS
SELECT quarantine_id, schema_name, table_name, severity,
       business_key, failure_reason,
       AGE(NOW(), quarantined_at) AS open_for,
       quarantined_at
  FROM quarantine.q_bad_rows
 WHERE status IN ('OPEN','IN_REVIEW')
   AND (
        (severity='CRITICAL' AND quarantined_at < NOW() - INTERVAL '4 hours')  OR
        (severity='HIGH'     AND quarantined_at < NOW() - INTERVAL '1 day')    OR
        (severity='MEDIUM'   AND quarantined_at < NOW() - INTERVAL '3 days')   OR
        (severity='LOW'      AND quarantined_at < NOW() - INTERVAL '7 days')
       );
