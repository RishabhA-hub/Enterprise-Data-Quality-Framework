# Step 6 — Quarantine Layer & Remediation Workflow

## Goal
Capture every failing row produced by the Rule Engine (Step 4), expose it
to data stewards with SLA tracking, and provide a controlled workflow to
fix, reprocess, or formally accept the defect.

## Architecture

```
RULES run (Step 4) ──► dq_rule_results (violation_count>0)
                              │
                              ▼
            quarantine_engine.py  (re-runs selectors, snapshots rows)
                              │
                              ▼
              quarantine.q_bad_rows  (JSONB payload + severity + status)
                              │              │
        remediate.py CLI ─────┘              ▼
                                  q_remediation_log (audit trail)
                                  v_open_by_table  (BI)
                                  v_sla_breaches   (alerts)
```

## What was built

| Artifact | Purpose |
|---|---|
| `sql/10_quarantine_layer.sql` | `quarantine` schema, `q_bad_rows`, `q_remediation_log`, trigger, views |
| `python/quarantine/quarantine_engine.py` | Captures failing rows from the latest RULES run |
| `python/quarantine/remediate.py` | CLI for stewards: list/assign/fix/reprocess/ignore/reject |

## Design highlights

- **Schema-flexible payload** — `JSONB` column means any table can be
  quarantined without schema changes; GIN index keeps queries fast.
- **Selector convention** — rule_sql is `SELECT COUNT(*) ... WHERE <bad>`;
  the engine auto-derives `SELECT * ... WHERE <bad>` to fetch actual rows.
  Override via the new `dq_rules.selector_sql` column when needed.
- **Lifecycle states** — `OPEN → IN_REVIEW → {FIXED, REPROCESSED, IGNORED, REJECTED}`
- **Auto audit log** — `AFTER UPDATE` trigger writes every status change.
- **SLA view** — `v_sla_breaches` flags critical defects open > 4 h,
  high > 1 d, medium > 3 d, low > 7 d.

## Usage

```bash
psql -f sql/10_quarantine_layer.sql

cd python
pip install -r requirements.txt
cp .env.example .env

# 1. Run rules first (Step 4)
python -m rules_engine.run_rules

# 2. Quarantine all failures from the latest rules run
python -m quarantine.quarantine_engine
# or from a specific run:
python -m quarantine.quarantine_engine --from-execution 42

# 3. Steward workflow
python -m quarantine.remediate list --status OPEN --severity HIGH
python -m quarantine.remediate assign 142 --to alice
python -m quarantine.remediate fix    142 --note "Source system patched"
python -m quarantine.remediate ignore 145 --note "Test account"
```

## Verification

```sql
-- Backlog by table + severity
SELECT * FROM quarantine.v_open_by_table ORDER BY open_count DESC;

-- SLA breaches that need escalation
SELECT * FROM quarantine.v_sla_breaches;

-- Full audit trail for a row
SELECT * FROM quarantine.q_remediation_log WHERE quarantine_id=142 ORDER BY acted_at;

-- Top failing rules this week
SELECT rule_code, COUNT(*) AS bad_rows
  FROM quarantine.q_bad_rows
 WHERE quarantined_at > NOW() - INTERVAL '7 days'
 GROUP BY rule_code ORDER BY bad_rows DESC;
```

## Fortune-500 practices applied
- **Separation of concerns** — bad data never blocks the pipeline; it
  diverts to quarantine while clean rows continue downstream
- **Auditability** — every state change recorded with actor + timestamp
- **SLA-driven triage** — severity drives the response clock
- **Self-service stewardship** — CLI today, web UI tomorrow
- **GDPR/PII-safe** — quarantine schema can be locked down separately

Next step (7): Orchestration & scheduling (Airflow/Prefect-style DAG).
