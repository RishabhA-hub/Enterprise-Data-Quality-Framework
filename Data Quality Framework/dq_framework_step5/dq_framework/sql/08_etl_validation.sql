-- ---------------------------------------------------------------------------
-- Step 5: ETL validation catalog + results table
-- ---------------------------------------------------------------------------

-- (Re)create etl_validation_results in case Step 1 stub differs
CREATE TABLE IF NOT EXISTS monitoring.etl_validation_results (
    result_id      BIGSERIAL PRIMARY KEY,
    execution_id   BIGINT NOT NULL
        REFERENCES monitoring.dq_execution_log(execution_id) ON DELETE CASCADE,
    job_id         INT,
    job_name       TEXT NOT NULL,
    check_type     TEXT NOT NULL,
    source_value   NUMERIC,
    target_value   NUMERIC,
    diff           NUMERIC,
    diff_pct       NUMERIC(12,6),
    tolerance_pct  NUMERIC(7,4) NOT NULL DEFAULT 0,
    status         TEXT NOT NULL CHECK (status IN ('PASS','WARN','FAIL','ERROR')),
    detail         TEXT,
    executed_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_etlres_exec    ON monitoring.etl_validation_results (execution_id);
CREATE INDEX IF NOT EXISTS ix_etlres_status  ON monitoring.etl_validation_results (status);
CREATE INDEX IF NOT EXISTS ix_etlres_job     ON monitoring.etl_validation_results (job_name);


CREATE TABLE IF NOT EXISTS monitoring.etl_validation_jobs (
    job_id         SERIAL PRIMARY KEY,
    job_name       TEXT NOT NULL UNIQUE,
    check_type     TEXT NOT NULL
        CHECK (check_type IN ('row_count','sum_check','distinct_check',
                              'null_check','orphan_check','hash_check')),
    source_sql     TEXT NOT NULL,
    target_sql     TEXT NOT NULL,
    tolerance_pct  NUMERIC(7,4) NOT NULL DEFAULT 0,
    is_active      BOOLEAN NOT NULL DEFAULT TRUE,
    description    TEXT,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- BI view: latest status per job
CREATE OR REPLACE VIEW monitoring.v_latest_etl_validation AS
SELECT DISTINCT ON (job_name)
       job_name, check_type, execution_id, source_value, target_value,
       diff, diff_pct, tolerance_pct, status, detail, executed_at
  FROM monitoring.etl_validation_results
 ORDER BY job_name, executed_at DESC;
