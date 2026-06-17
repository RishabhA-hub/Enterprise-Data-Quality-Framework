# Step 1 — Database Design

## 1. Architecture: 3-layer pattern

```
SOURCE FILES ──▶ staging.*  ──▶ [DQ engine + ETL validator] ──▶ clean.*
                     │                                              │
                     └──────────▶ monitoring.* (logs, rules, scores, recon)
```

| Layer | Schema | Purpose | Constraints |
|---|---|---|---|
| Raw | `staging` | Land source data exactly as received | None (TEXT-heavy, no PK/FK) |
| Quality | `monitoring` | Rule repository, run logs, scores, ETL recon | Strong PK/FK, CHECK constraints |
| Conformed | `clean` | Star schema for BI / Power BI | Surrogate keys, FKs, CHECKs, SCD-2 columns |

**Why three layers?** You cannot measure quality on a table that already rejects bad rows. Staging deliberately accepts garbage so the engine can *quantify* it. Monitoring captures the evidence. Clean is the trustworthy publish layer that Power BI consumes.

## 2. Table inventory

**Staging** — `stg_customer`, `stg_sales`, `stg_employee`
Datatypes are deliberately permissive (e.g., `registration_date TEXT`) to preserve malformed values so validity rules can catch them. Every row carries `load_id` + `load_ts` for batch lineage.

**Monitoring**
- `dq_execution_log` — one row per pipeline run (the "run header"). All other monitoring tables FK to it, enabling time-series trend analysis.
- `dq_rules` — metadata-driven rule repository. `rule_sql` stores the violation-count query so new rules require zero code changes.
- `dq_rule_results` — per-run, per-rule violations. Generated column `pass_rate_pct` removes drift between Python and SQL.
- `dq_quality_scores` — per-run, per-table dimension scores with weights (drives the enterprise DQ score in Step 6).
- `etl_validation_results` — source-vs-target reconciliation (row count, sum, hash, PK/FK).

**Clean (Kimball star)**
- `dim_customer`, `dim_employee` — SCD-2 ready (`effective_from`, `effective_to`, `is_current`). Surrogate `_sk` keys decouple warehouse from source IDs.
- `fact_sales` — grain = one order line. FK to `dim_customer`, business key `order_bk` UNIQUE for idempotent reloads, `load_execution_id` for lineage back to monitoring.

## 3. Key design decisions

| Decision | Rationale |
|---|---|
| Separate `staging` schema with no constraints | Quality must be observed, not silently rejected at the boundary. |
| `TEXT` for dates/emails/phones in staging | Capture format defects (Step 2 injects these). |
| Surrogate `BIGSERIAL` keys in `clean` | Standard Kimball practice — supports SCD-2, reload safety, and joins on small integers. |
| `GENERATED ALWAYS AS ... STORED` for `pass_rate_pct` and `variance` | Single source of truth — Python and BI compute the same number. |
| `CHECK` constraints on dimensions/facts | Defense in depth — even if cleansing has a bug, bad rows can't reach BI. |
| Metadata-driven rules table | Add/disable rules at runtime without redeploying Python. |
| `execution_id` FK on every monitoring child | Enables trend dashboards: "show me last 30 runs of pipeline X". |
| `CHECK` on `dimension`, `severity`, `status` enums | Constrain vocabulary so dashboards aren't polluted by typos. |
| Indexes on FKs and `load_id` | DQ queries are mostly aggregations by run — indexes keep them sub-second on million-row staging tables. |

## 4. ER diagram

See `diagrams/er_diagram.mmd` (Mermaid, renders in GitHub / VS Code).

## 5. How to run

```bash
psql -U postgres -d dq_framework -f sql/01_create_schemas.sql
psql -U postgres -d dq_framework -f sql/02_staging_layer.sql
psql -U postgres -d dq_framework -f sql/03_monitoring_layer.sql
psql -U postgres -d dq_framework -f sql/04_clean_layer.sql
psql -U postgres -d dq_framework -f sql/05_seed_rules.sql
```

## 6. Verification

```sql
-- All three schemas exist
SELECT schema_name FROM information_schema.schemata
WHERE schema_name IN ('staging','monitoring','clean');

-- All ten tables exist
SELECT table_schema, table_name FROM information_schema.tables
WHERE table_schema IN ('staging','monitoring','clean')
ORDER BY table_schema, table_name;

-- 8 baseline rules seeded
SELECT rule_id, dimension, severity FROM monitoring.dq_rules ORDER BY rule_id;
```

Expected: 3 schemas, 10 tables, 8 rules.

---
Next: **Step 2 — Data Corruption Simulation** (Python generators that inject the 6 issue families into the staging tables so the engine has something real to measure).
