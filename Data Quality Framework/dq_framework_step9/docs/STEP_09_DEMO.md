# Step 9 — End-to-End Demo Dataset & Runner

This step turns the framework from "set of components" into a **runnable,
reproducible demo** that a reviewer can clone and execute in under two
minutes. Every component built in Steps 1-8 is exercised against a
realistic dataset that contains intentional, catalogued defects.

## What's in the box

| File | Purpose |
| --- | --- |
| `sql/20_demo_schema.sql` | Source (`demo_src`) + warehouse (`demo_tgt`) schemas. |
| `sql/21_demo_rules.sql`  | Seeds 8 DQ rules across all 7 DAMA dimensions + 1 ETL recon pair. |
| `scripts/generate_demo_data.py` | Synthesises 5K customers, 12K orders, ~28K items with **catalogued defects**. |
| `scripts/load_demo.sh` | COPYs CSVs into `demo_src`, seeds `demo_tgt` with a deliberate ETL gap. |
| `scripts/run_e2e_demo.sh` | One-shot runner: schema → data → rules → engines → exports → summary. |

## Catalogued defects (so reviewers know what *should* surface)

| Defect | Rate | Rule / artefact that catches it |
| --- | --- | --- |
| NULL email | ~3% of customers | `customers_email_completeness` (COMPLETENESS / HIGH) |
| Malformed email | ~2% | `customers_email_validity` (VALIDITY / MEDIUM) |
| Duplicate `customer_id` | 5 rows | `customers_uniqueness` (UNIQUENESS / CRITICAL) |
| Negative qty | ~0.3% of items | `order_items_negative_qty` (VALIDITY / HIGH) |
| `total_amount` ≠ Σ`line_amount` | ~1% of orders | `orders_total_consistency` (CONSISTENCY / HIGH) |
| Orphan `order_items` | ~0.2% | `order_items_orphan` (REFERENTIAL / CRITICAL) |
| Future-dated orders | ~0.5% | `orders_future_dated` (TIMELINESS / HIGH) |
| Bad currency code | ~0.4% | `orders_currency_validity` (VALIDITY / HIGH) |
| Source rows missing in target | ~0.7% | `etl_recon` pair `orders_src_to_fact` |

Every defect type maps to a different dimension, so the executive
scorecard from Step 8 lights up across the full DAMA wheel — not just a
single column.

## How to run

```bash
export PGHOST=...  PGUSER=...  PGPASSWORD=...  PGDATABASE=...
export DQ_FRAMEWORK_ROOT=/path/to/dq_framework   # where steps 1-8 are unzipped

cd dq_framework_step9
bash scripts/run_e2e_demo.sh
```

Expected runtime on a laptop: **60-90 seconds**. The runner tees a
timestamped log file you can attach to a PR or run review.

### What you'll see at the end

1. A per-dimension summary table — rules run, passed, failed, failed rows.
2. A quarantine status breakdown (`OPEN`, `IN_REVIEW`, etc.).
3. CSV + XLSX + HTML exports under `./exports/` from `scorecard_exporter.py`.
4. The executive scorecard view (`reporting.v_executive_scorecard`) populated
   with the latest run.

## Why this matters (Fortune-500 lens)

- **Reproducibility** — same seed, same defects, same numbers every run.
  Auditors and new joiners can verify the framework behaves as claimed.
- **Coverage proof** — the defect catalogue is a 1:1 mapping to rules,
  so a missing detection is immediately obvious.
- **Onboarding** — a new data steward can run this once and understand
  the full pipeline without touching production.
- **Regression harness** — wire `run_e2e_demo.sh` into CI; if a code
  change drops detection of a known defect, the build fails.

## Next

Reply **next** for **Step 10 — Governance, RBAC & Audit Hardening**:
least-privilege roles for stewards/engineers/viewers, immutable audit
log with hash-chaining, and a published runbook for incident response.
