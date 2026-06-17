# Step 4 — Rule Execution Engine

## Goal
Execute every active rule in `monitoring.dq_rules` against the staging
layer, persist per-rule outcomes, and roll up weighted quality scores
across the six DQ dimensions.

## Architecture

```
 dq_rules (metadata) ──► engine.execute_rule() ──► dq_rule_results
                                                        │
                                                        ▼
                                            dq_quality_scores (per table)
                                                        │
                                                        ▼
                                       v_latest_quality_scores (BI view)
```

## What was built

| Artifact | Purpose |
|---|---|
| `sql/07_rule_results_and_scores.sql` | DDL for `dq_rule_results`, `dq_quality_scores`, view |
| `python/rules_engine/engine.py` | Core runner — fetch rules, execute, persist, rollup |
| `python/rules_engine/run_rules.py` | CLI entry point |
| `python/rules_engine/db.py` | Connection helper |

## Rule contract
Every row in `dq_rules.rule_sql` MUST be a SELECT returning a single
integer — the count of violating rows in the target table. Example:

```sql
-- DQ001 — completeness: customer_id never null
SELECT COUNT(*) FROM staging.stg_customer WHERE customer_id IS NULL;
```

## Status thresholds
- `PASS`  — pass_rate ≥ threshold_pct
- `WARN`  — within 5 pp below threshold
- `FAIL`  — more than 5 pp below threshold
- `ERROR` — SQL exception (logged in `error_msg`)

## Dimension weights (default)
| Dimension | Weight |
|---|---|
| completeness | 0.25 |
| validity     | 0.20 |
| uniqueness   | 0.15 |
| consistency  | 0.15 |
| accuracy     | 0.15 |
| timeliness   | 0.10 |

Weights are renormalized over dimensions actually present for a table.

## Usage

```bash
psql -f sql/07_rule_results_and_scores.sql

cd python
pip install -r requirements.txt
cp .env.example .env

python -m rules_engine.run_rules                  # all tables
python -m rules_engine.run_rules --table stg_sales
```

## Verification

```sql
-- latest run summary
SELECT execution_id, status, started_at, ended_at, notes
  FROM monitoring.dq_execution_log
 WHERE run_type='RULES'
 ORDER BY execution_id DESC LIMIT 1;

-- failures only
SELECT rule_id, schema_name, table_name, dimension,
       violation_count, pass_rate_pct, status
  FROM monitoring.dq_rule_results
 WHERE execution_id = :eid AND status <> 'PASS';

-- BI scorecard
SELECT * FROM monitoring.v_latest_quality_scores;
```

## Fortune-500 practices applied
- **Metadata-driven** — new rule = new row, no code deploy
- **Idempotent runs** — every execution gets its own `execution_id`
- **Auditability** — every result row references the rule + run
- **Graceful degradation** — bad SQL becomes `ERROR`, doesn't kill the run
- **Weighted scorecards** — directly consumable by Power BI / Tableau

Next step (5): ETL validation & source-to-target reconciliation.
