-- =====================================================================
-- MONITORING LAYER
-- Every DQ run is a transaction:
--   1. dq_execution_log     -> one row per pipeline run (header)
--   2. dq_rule_results      -> one row per (run, rule, table) (detail)
--   3. dq_quality_scores    -> one row per (run, table, dimension)
--   4. etl_validation_results -> reconciliation source vs target
-- All four reference dq_execution_log.execution_id so we can trend
-- enterprise quality over time and drill from KPI down to row-level cause.
-- =====================================================================

-- ---------- 3.1 Execution log (the "run header") ----------
DROP TABLE IF EXISTS monitoring.dq_execution_log CASCADE;
CREATE TABLE monitoring.dq_execution_log (
    execution_id     BIGSERIAL   PRIMARY KEY,
    pipeline_name    TEXT        NOT NULL,
    run_started_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    run_ended_at     TIMESTAMPTZ,
    status           TEXT        NOT NULL DEFAULT 'RUNNING'
                                 CHECK (status IN ('RUNNING','SUCCESS','FAILED','PARTIAL')),
    records_in       BIGINT,
    records_out      BIGINT,
    triggered_by     TEXT,
    notes            TEXT
);

-- ---------- 3.2 Rule repository (metadata-driven) ----------
DROP TABLE IF EXISTS monitoring.dq_rules CASCADE;
CREATE TABLE monitoring.dq_rules (
    rule_id         TEXT        PRIMARY KEY,           -- e.g. DQ001
    rule_name       TEXT        NOT NULL,
    target_table    TEXT        NOT NULL,              -- e.g. staging.stg_customer
    target_column   TEXT,                              -- nullable for multi-col rules
    dimension       TEXT        NOT NULL
                                CHECK (dimension IN
                                ('Completeness','Accuracy','Consistency',
                                 'Validity','Uniqueness','Integrity')),
    severity        TEXT        NOT NULL DEFAULT 'HIGH'
                                CHECK (severity IN ('LOW','MEDIUM','HIGH','CRITICAL')),
    rule_sql        TEXT        NOT NULL,              -- SELECT count(*) ... violations
    description     TEXT,
    is_active       BOOLEAN     NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------- 3.3 Rule results ----------
DROP TABLE IF EXISTS monitoring.dq_rule_results CASCADE;
CREATE TABLE monitoring.dq_rule_results (
    result_id        BIGSERIAL   PRIMARY KEY,
    execution_id     BIGINT      NOT NULL REFERENCES monitoring.dq_execution_log(execution_id) ON DELETE CASCADE,
    rule_id          TEXT        NOT NULL REFERENCES monitoring.dq_rules(rule_id),
    target_table     TEXT        NOT NULL,
    records_checked  BIGINT      NOT NULL,
    records_failed   BIGINT      NOT NULL,
    pass_rate_pct    NUMERIC(6,3) GENERATED ALWAYS AS
        (CASE WHEN records_checked = 0 THEN 100
              ELSE 100.0 * (records_checked - records_failed) / records_checked END) STORED,
    status           TEXT        NOT NULL
                                 CHECK (status IN ('PASS','FAIL','WARN')),
    executed_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_dqrr_exec ON monitoring.dq_rule_results(execution_id);
CREATE INDEX idx_dqrr_rule ON monitoring.dq_rule_results(rule_id);

-- ---------- 3.4 Quality scores (per dimension) ----------
DROP TABLE IF EXISTS monitoring.dq_quality_scores CASCADE;
CREATE TABLE monitoring.dq_quality_scores (
    score_id          BIGSERIAL   PRIMARY KEY,
    execution_id      BIGINT      NOT NULL REFERENCES monitoring.dq_execution_log(execution_id) ON DELETE CASCADE,
    target_table      TEXT        NOT NULL,
    dimension         TEXT        NOT NULL
                                  CHECK (dimension IN
                                  ('Completeness','Accuracy','Consistency',
                                   'Validity','Uniqueness','Integrity','Overall')),
    dimension_score   NUMERIC(6,3) NOT NULL CHECK (dimension_score BETWEEN 0 AND 100),
    weight_pct        NUMERIC(5,2) NOT NULL,
    weighted_score    NUMERIC(6,3) NOT NULL,
    computed_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (execution_id, target_table, dimension)
);

-- ---------- 3.5 ETL reconciliation ----------
DROP TABLE IF EXISTS monitoring.etl_validation_results CASCADE;
CREATE TABLE monitoring.etl_validation_results (
    validation_id    BIGSERIAL   PRIMARY KEY,
    execution_id     BIGINT      NOT NULL REFERENCES monitoring.dq_execution_log(execution_id) ON DELETE CASCADE,
    check_type       TEXT        NOT NULL
                                 CHECK (check_type IN
                                 ('ROW_COUNT','SUM','HASH_TOTAL','DUPLICATE',
                                  'NULL_CHECK','PRIMARY_KEY','FOREIGN_KEY')),
    source_object    TEXT        NOT NULL,
    target_object    TEXT        NOT NULL,
    source_value     NUMERIC(20,4),
    target_value     NUMERIC(20,4),
    variance         NUMERIC(20,4) GENERATED ALWAYS AS
                     (COALESCE(target_value,0) - COALESCE(source_value,0)) STORED,
    status           TEXT        NOT NULL CHECK (status IN ('PASS','FAIL')),
    executed_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_etl_val_exec ON monitoring.etl_validation_results(execution_id);
