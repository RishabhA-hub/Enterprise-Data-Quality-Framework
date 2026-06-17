# Step 3 — Data Profiling Engine

## Goal
Auto-discover the **shape and health** of every staging table before any DQ
rule fires. Profiling answers: *"What does this column actually look like?"*

## What it computes (per column)
| Metric | Why it matters |
|---|---|
| `row_count`, `null_count`, `null_pct` | Completeness baseline |
| `distinct_count`, `distinct_pct` | Cardinality / candidate-key detection |
| `min` / `max` / `mean` / `stddev` (numeric) | Range & outlier scoping |
| `min_length` / `max_length` (text) | Format anomalies |
| `top_values` (top-5) | Frequency hotspots & sentinel detection (`'NA'`, `'-'`) |
| `inferred_type` | Semantic typing (email / phone / date / integer / decimal / uuid / text) via regex voting on a 500-row sample |

## Architecture
```
staging.stg_*  ──►  profiler.profile_table()  ──►  pandas.DataFrame
                                                       │
                                                       ├─► CSV (--out)
                                                       └─► monitoring.dq_profile_results (--persist)
```

Every persisted run is wrapped in a `monitoring.dq_execution_log` row
(`run_type = 'PROFILE'`) so profiles are tied to a reproducible execution_id —
the same lineage model Step 4 (rule engine) will reuse.

## Files
| File | Purpose |
|---|---|
| `sql/06_profile_table.sql` | DDL for `monitoring.dq_profile_results` |
| `profiling/db.py` | `psycopg2` connection helper, `.env` driven |
| `profiling/profiler.py` | Core profiling logic + semantic-type inference |
| `profiling/run_profiler.py` | CLI runner |
| `profiling/requirements.txt` | Python deps |
| `profiling/.env.example` | DB connection template |

## Install & run
```bash
cd profiling
python -m pip install -r requirements.txt
cp .env.example .env       # edit credentials
psql -f ../sql/06_profile_table.sql

# print profile for every stg_* table
python run_profiler.py

# profile one table + write CSV + persist to monitoring
python run_profiler.py --table stg_customer --persist --out customer_profile.csv
```

## Sample output (truncated)
```
column_name  inferred_type  row_count  null_pct  distinct_pct
customer_id  integer            5000      0.00         99.98
email        email              5000      4.10         95.20
phone        phone_us           5000      2.80         93.10
signup_date  date_iso           5000      1.20         12.40
country      text               5000      0.00          0.40
```

## Best-practice notes (Fortune-500 framing)
1. **Profile BEFORE you rule.** Hard-coding a rule like *"email must match
   regex X"* without first profiling guarantees false positives on systems
   that use multiple legitimate formats (e.g. legacy CRM vs. e-commerce).
2. **Track profile drift.** Re-running the profiler on every load and storing
   results in `dq_profile_results` lets BI dashboards trend
   `null_pct`, `distinct_pct`, and `inferred_type` over time — the earliest
   signal of upstream schema change.
3. **Use inferred type to auto-suggest rules.** A column inferred as `email`
   can auto-attach the regex completeness/format rule from `dq_rules`,
   removing manual rule-mapping overhead.
4. **Sample, don't scan, for type inference.** 500 rows is enough to win the
   regex vote with >99% confidence on 5k–5M row tables, keeping profile
   runtime O(seconds).

## Next
Step 4 — **Rule Execution Engine**: read `monitoring.dq_rules`, execute each
rule's SQL against staging, write violations to `dq_rule_results`, and roll
up to `dq_quality_scores` per dimension (Completeness, Validity, Uniqueness,
Integrity, Accuracy, Consistency, Timeliness).
