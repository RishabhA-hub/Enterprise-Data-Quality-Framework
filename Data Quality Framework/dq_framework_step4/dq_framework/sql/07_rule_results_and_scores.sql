-- ---------------------------------------------------------------------------
-- Step 4 schema additions: per-run rule results + dimension score rollups
-- Safe to re-run (IF NOT EXISTS).
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS monitoring.dq_rule_results (
    result_id        BIGSERIAL PRIMARY KEY,
    execution_id     BIGINT      NOT NULL
        REFERENCES monitoring.dq_execution_log(execution_id) ON DELETE CASCADE,
    rule_id          INT         NOT NULL
        REFERENCES monitoring.dq_rules(rule_id),
    schema_name      TEXT        NOT NULL,
    table_name       TEXT        NOT NULL,
    column_name      TEXT,
    dimension        TEXT        NOT NULL,
    severity         TEXT        NOT NULL,
    total_rows       BIGINT      NOT NULL DEFAULT 0,
    violation_count  BIGINT      NOT NULL DEFAULT 0,
    pass_rate_pct    NUMERIC(7,4) GENERATED ALWAYS AS (
        CASE WHEN total_rows = 0 THEN 100
             ELSE ROUND((total_rows - violation_count) * 100.0 / total_rows, 4)
        END
    ) STORED,
    status           TEXT        NOT NULL
        CHECK (status IN ('PASS','WARN','FAIL','ERROR')),
    error_msg        TEXT,
    executed_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_rule_results_exec
    ON monitoring.dq_rule_results (execution_id);
CREATE INDEX IF NOT EXISTS ix_rule_results_table
    ON monitoring.dq_rule_results (schema_name, table_name);
CREATE INDEX IF NOT EXISTS ix_rule_results_status
    ON monitoring.dq_rule_results (status);


CREATE TABLE IF NOT EXISTS monitoring.dq_quality_scores (
    score_id            BIGSERIAL PRIMARY KEY,
    execution_id        BIGINT      NOT NULL
        REFERENCES monitoring.dq_execution_log(execution_id) ON DELETE CASCADE,
    schema_name         TEXT        NOT NULL,
    table_name          TEXT        NOT NULL,
    completeness_score  NUMERIC(7,4),
    validity_score      NUMERIC(7,4),
    uniqueness_score    NUMERIC(7,4),
    consistency_score   NUMERIC(7,4),
    accuracy_score      NUMERIC(7,4),
    timeliness_score    NUMERIC(7,4),
    overall_score       NUMERIC(7,4),
    total_rules_run     INT,
    total_violations    BIGINT,
    scored_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (execution_id, schema_name, table_name)
);

CREATE INDEX IF NOT EXISTS ix_scores_table
    ON monitoring.dq_quality_scores (schema_name, table_name);
CREATE INDEX IF NOT EXISTS ix_scores_exec
    ON monitoring.dq_quality_scores (execution_id);


-- Convenience view: latest score per table
CREATE OR REPLACE VIEW monitoring.v_latest_quality_scores AS
SELECT DISTINCT ON (schema_name, table_name)
       schema_name, table_name, execution_id, overall_score,
       completeness_score, validity_score, uniqueness_score,
       consistency_score, accuracy_score, timeliness_score,
       total_rules_run, total_violations, scored_at
  FROM monitoring.dq_quality_scores
 ORDER BY schema_name, table_name, scored_at DESC;
