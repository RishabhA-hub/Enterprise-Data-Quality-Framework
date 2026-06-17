-- =====================================================================
-- Step 8 — Reporting Layer: BI-ready views for Power BI / Tableau / Looker
-- =====================================================================
-- Design notes (Fortune-500 alignment):
--   * Views live in a dedicated `reporting` schema so BI service accounts
--     can be granted SELECT without exposing raw operational tables.
--   * All views are additive (no DROP of existing objects from prior steps).
--   * Column names use snake_case + business-friendly aliases for self-serve.
--   * Time grain is normalized to UTC; BI tools localize at the semantic layer.
-- =====================================================================

CREATE SCHEMA IF NOT EXISTS reporting;

-- ---------------------------------------------------------------------
-- 1. Executive scorecard (one row per execution) — landing page KPI tile
-- ---------------------------------------------------------------------
CREATE OR REPLACE VIEW reporting.v_executive_scorecard AS
SELECT
    e.execution_id,
    e.pipeline_name,
    e.triggered_by,
    e.started_at,
    e.finished_at,
    EXTRACT(EPOCH FROM (e.finished_at - e.started_at))::INT  AS duration_seconds,
    e.status                                                  AS execution_status,
    COALESCE(r.rules_total, 0)                                AS rules_total,
    COALESCE(r.rules_pass,  0)                                AS rules_pass,
    COALESCE(r.rules_warn,  0)                                AS rules_warn,
    COALESCE(r.rules_fail,  0)                                AS rules_fail,
    CASE WHEN COALESCE(r.rules_total,0) = 0 THEN NULL
         ELSE ROUND(100.0 * r.rules_pass / r.rules_total, 2)
    END                                                       AS rule_pass_pct,
    COALESCE(v.etl_total, 0)                                  AS etl_checks_total,
    COALESCE(v.etl_pass,  0)                                  AS etl_checks_pass,
    COALESCE(v.etl_fail,  0)                                  AS etl_checks_fail,
    COALESCE(q.quarantined_rows, 0)                           AS rows_quarantined
FROM   dq_execution_log e
LEFT JOIN LATERAL (
    SELECT COUNT(*)                                       AS rules_total,
           COUNT(*) FILTER (WHERE status='PASS')          AS rules_pass,
           COUNT(*) FILTER (WHERE status='WARN')          AS rules_warn,
           COUNT(*) FILTER (WHERE status='FAIL')          AS rules_fail
    FROM   dq_rule_results
    WHERE  execution_id = e.execution_id
) r ON TRUE
LEFT JOIN LATERAL (
    SELECT COUNT(*)                                       AS etl_total,
           COUNT(*) FILTER (WHERE status='PASS')          AS etl_pass,
           COUNT(*) FILTER (WHERE status IN ('FAIL','ERROR')) AS etl_fail
    FROM   etl_validation_results
    WHERE  execution_id = e.execution_id
) v ON TRUE
LEFT JOIN LATERAL (
    SELECT COUNT(*) AS quarantined_rows
    FROM   quarantine.q_bad_rows
    WHERE  execution_id = e.execution_id
) q ON TRUE;

-- ---------------------------------------------------------------------
-- 2. Rule-level detail (long format) — drill-down from scorecard
-- ---------------------------------------------------------------------
CREATE OR REPLACE VIEW reporting.v_rule_results_detail AS
SELECT
    r.result_id,
    r.execution_id,
    e.started_at::DATE        AS run_date,
    e.pipeline_name,
    r.rule_id,
    r.rule_name,
    r.dimension,
    r.target_table,
    r.target_column,
    r.severity,
    r.status,
    r.failed_rows,
    r.total_rows,
    CASE WHEN r.total_rows > 0
         THEN ROUND(100.0 * r.failed_rows / r.total_rows, 4)
         ELSE 0 END           AS failure_rate_pct,
    r.executed_at
FROM   dq_rule_results r
JOIN   dq_execution_log e USING (execution_id);

-- ---------------------------------------------------------------------
-- 3. Dimension trend — DAMA-DMBOK 6 dimensions, time series
-- ---------------------------------------------------------------------
CREATE OR REPLACE VIEW reporting.v_dimension_trend AS
SELECT
    e.started_at::DATE                                  AS run_date,
    r.dimension,
    COUNT(*)                                            AS checks_total,
    COUNT(*) FILTER (WHERE r.status='PASS')             AS checks_pass,
    ROUND(100.0 * COUNT(*) FILTER (WHERE r.status='PASS')
                / NULLIF(COUNT(*),0), 2)                AS pass_pct
FROM   dq_rule_results r
JOIN   dq_execution_log e USING (execution_id)
GROUP  BY 1, 2;

-- ---------------------------------------------------------------------
-- 4. Table health heat-map — for tile / matrix visuals
-- ---------------------------------------------------------------------
CREATE OR REPLACE VIEW reporting.v_table_health AS
SELECT
    target_table,
    COUNT(*)                                            AS checks_total,
    COUNT(*) FILTER (WHERE status='FAIL')               AS checks_fail,
    COUNT(*) FILTER (WHERE status='WARN')               AS checks_warn,
    ROUND(100.0 * COUNT(*) FILTER (WHERE status='PASS')
                / NULLIF(COUNT(*),0), 2)                AS health_score_pct,
    MAX(executed_at)                                    AS last_checked_at
FROM   dq_rule_results
WHERE  executed_at > NOW() - INTERVAL '30 days'
GROUP  BY target_table;

-- ---------------------------------------------------------------------
-- 5. Quarantine backlog by age bucket — operational ops view
-- ---------------------------------------------------------------------
CREATE OR REPLACE VIEW reporting.v_quarantine_backlog AS
SELECT
    source_table,
    severity,
    status,
    COUNT(*) AS open_rows,
    SUM(CASE WHEN AGE(NOW(), quarantined_at) <  INTERVAL '1 day'  THEN 1 ELSE 0 END) AS lt_1d,
    SUM(CASE WHEN AGE(NOW(), quarantined_at) BETWEEN INTERVAL '1 day' AND INTERVAL '7 day' THEN 1 ELSE 0 END) AS d1_7,
    SUM(CASE WHEN AGE(NOW(), quarantined_at) > INTERVAL '7 day' THEN 1 ELSE 0 END) AS gt_7d
FROM   quarantine.q_bad_rows
WHERE  status IN ('OPEN','IN_REVIEW')
GROUP  BY source_table, severity, status;

-- ---------------------------------------------------------------------
-- 6. Alert feed — anything that should page on-call
-- ---------------------------------------------------------------------
CREATE OR REPLACE VIEW reporting.v_active_alerts AS
SELECT
    'RULE_FAIL'              AS alert_type,
    r.severity,
    r.rule_name              AS subject,
    r.target_table           AS object,
    r.failed_rows            AS magnitude,
    r.executed_at            AS triggered_at
FROM   dq_rule_results r
WHERE  r.status = 'FAIL'
  AND  r.severity IN ('HIGH','CRITICAL')
  AND  r.executed_at > NOW() - INTERVAL '24 hours'
UNION ALL
SELECT
    'ETL_RECON_FAIL',
    'HIGH',
    job_name,
    NULL,
    ABS(COALESCE(source_value,0) - COALESCE(target_value,0))::BIGINT,
    executed_at
FROM   etl_validation_results
WHERE  status IN ('FAIL','ERROR')
  AND  executed_at > NOW() - INTERVAL '24 hours'
UNION ALL
SELECT
    'SLA_BREACH',
    severity,
    'Quarantine row #' || quarantine_id,
    source_table,
    1,
    quarantined_at
FROM   quarantine.v_sla_breaches;

-- ---------------------------------------------------------------------
-- Grants — BI reader role (create role separately in prod)
-- ---------------------------------------------------------------------
-- CREATE ROLE bi_reader NOLOGIN;
-- GRANT USAGE ON SCHEMA reporting TO bi_reader;
-- GRANT SELECT ON ALL TABLES IN SCHEMA reporting TO bi_reader;
-- ALTER DEFAULT PRIVILEGES IN SCHEMA reporting
--     GRANT SELECT ON TABLES TO bi_reader;
