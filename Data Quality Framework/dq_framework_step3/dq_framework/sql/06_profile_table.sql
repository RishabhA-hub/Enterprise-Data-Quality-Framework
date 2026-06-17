-- Step 3: profiling results table
-- Stores one row per (execution, schema, table, column)

CREATE TABLE IF NOT EXISTS monitoring.dq_profile_results (
    profile_id       BIGSERIAL PRIMARY KEY,
    execution_id     BIGINT NOT NULL REFERENCES monitoring.dq_execution_log(execution_id),
    schema_name      TEXT   NOT NULL,
    table_name       TEXT   NOT NULL,
    column_name      TEXT   NOT NULL,
    data_type        TEXT,
    inferred_type    TEXT,
    row_count        BIGINT,
    null_count       BIGINT,
    null_pct         NUMERIC(6,2),
    distinct_count   BIGINT,
    distinct_pct     NUMERIC(6,2),
    min_value        TEXT,
    max_value        TEXT,
    mean_value       DOUBLE PRECISION,
    stddev_value     DOUBLE PRECISION,
    min_length       INT,
    max_length       INT,
    top_values       TEXT,
    profiled_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_profile_exec        ON monitoring.dq_profile_results(execution_id);
CREATE INDEX IF NOT EXISTS ix_profile_table_col   ON monitoring.dq_profile_results(schema_name, table_name, column_name);
