# Step 5 — ETL Validation & Source-to-Target Reconciliation

## Goal
Prove the staging → clean ETL preserved the data: row counts, sum totals,
distinct keys, NULL counts, and FK integrity all reconcile within
defined tolerances.

## What was built

| Artifact | Purpose |
|---|---|
| `sql/08_etl_validation.sql` | `etl_validation_jobs` catalog, results table, BI view |
| `sql/09_seed_etl_jobs.sql` | 9 baseline reconciliation jobs |
| `python/etl_validator/validator.py` | Engine — runs jobs, compares, persists |
| `python/etl_validator/run_validation.py` | CLI entry point |

## Check types supported
| Type | Compares | Typical tolerance |
|---|---|---|
| `row_count` | `COUNT(*)` source vs target | 0–0.5% |
| `sum_check` | `SUM(measure)` | 0–0.01% (rounding) |
| `distinct_check` | `COUNT(DISTINCT bk)` | 0 |
| `null_check` | `COUNT(*) WHERE col IS NULL` | 0 |
| `orphan_check` | LEFT JOIN orphans (target side) | 0 |
| `hash_check` | MD5 row-hash matches | 0 |

## Job contract
Each row in `etl_validation_jobs` provides:
- `source_sql` — returns ONE scalar value from staging
- `target_sql` — returns ONE scalar value from clean
- `tolerance_pct` — allowed % delta before failing

Status thresholds:
- `PASS`  → diff_pct == 0
- `WARN`  → 0 < diff_pct ≤ tolerance
- `FAIL`  → diff_pct > tolerance
- `ERROR` → SQL exception (`detail` populated)

## Usage

```bash
psql -f sql/08_etl_validation.sql
psql -f sql/09_seed_etl_jobs.sql

cd python
pip install -r requirements.txt
cp .env.example .env

python -m etl_validator.run_validation                      # all jobs
python -m etl_validator.run_validation --job sales_amount_sum
```

## Verification

```sql
-- latest reconciliation summary
SELECT * FROM monitoring.v_latest_etl_validation
 ORDER BY status DESC, job_name;

-- failures from last run
SELECT job_name, check_type, source_value, target_value,
       diff, diff_pct, tolerance_pct, detail
  FROM monitoring.etl_validation_results
 WHERE execution_id = (SELECT MAX(execution_id) FROM monitoring.dq_execution_log
                        WHERE run_type='ETL_RECON')
   AND status <> 'PASS';
```

## Fortune-500 practices applied
- **Tolerance-based comparisons** — handles legitimate rounding/conversion
- **Catalog-driven** — auditors see all controls in one table
- **Tied to execution_id** — every reconciliation traceable end-to-end
- **Orphan checks** — guarantees referential integrity post-load
- **SOX / BCBS-239 ready** — controls catalog + evidence in one place

Next step (6): Quarantine layer + remediation workflow.
