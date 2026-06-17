# Step 7 — Orchestration & Scheduling

## Goal
Wire every previously-built module (generators → profiler → rules engine →
ETL reconciliation → quarantine → scorecard → notify) into a single
schedulable pipeline with retries, SLAs, and observability.

## DAG

```
start ─► extract ─► profile ─► rules ─┬─► etl_recon ─┐
                                      └─► quarantine ┘─► scorecard ─► notify ─► end
```

`rules` is the only "gate" task — it MUST run before recon/quarantine can
look at violations. Everything after `rules` uses `trigger_rule=all_done`
so a single failure does not skip downstream evidence collection.

## Deliverables

| Path | Purpose |
|---|---|
| `orchestration/airflow/dags/dq_framework_daily.py` | Production Airflow 2.x DAG |
| `orchestration/prefect/dq_flow.py` | Prefect 2.x equivalent |
| `orchestration/local/run_pipeline.sh` | Cron / dev runner (no scheduler needed) |
| `diagrams/dag_flow.mmd` | Mermaid diagram of the pipeline |

## Design choices (Fortune-500)

- **Thin orchestrator** — the DAG calls existing Python modules; no
  business logic lives in the DAG file. Schedulers stay swappable
  (Airflow ↔ Prefect ↔ cron) without rewrites.
- **Non-blocking quality gates** — bad rows go to quarantine instead of
  failing the pipeline, so downstream teams still get a scorecard.
- **Secrets via Airflow Connection** (`dq_postgres`) — no credentials in
  code, fully compatible with Vault / AWS Secrets Manager backends.
- **SLA tracking** — 20-min per-task SLA; misses fire `sla_miss_callback`
  (plug in PagerDuty / Slack / Teams).
- **Retries** — exponential by default (`retries=2, retry_delay=5m`).
- **Idempotent** — every run opens its own `execution_id`; re-runs never
  corrupt history.
- **Observability** — `triggered_by=airflow` tag flows into
  `monitoring.dq_execution_log` for forensic queries.

## Airflow deployment

```bash
# 1. Drop DAG file into Airflow
cp orchestration/airflow/dags/dq_framework_daily.py $AIRFLOW_HOME/dags/

# 2. Register Postgres connection once
airflow connections add dq_postgres \
    --conn-type postgres --conn-host db.internal --conn-port 5432 \
    --conn-schema dq_framework --conn-login etl --conn-password ***

# 3. Mount the framework code
ln -s /repo/dq_framework /opt/dq_framework

# 4. Unpause + trigger smoke test
airflow dags unpause dq_framework_daily
airflow dags trigger dq_framework_daily
```

## Prefect deployment

```bash
prefect deployment build orchestration/prefect/dq_flow.py:dq_pipeline \
    -n daily --cron "0 2 * * *" -q default
prefect deployment apply dq_pipeline-deployment.yaml
prefect agent start -q default
```

## Local / cron

```bash
chmod +x orchestration/local/run_pipeline.sh
crontab -e
# add:  0 2 * * *  /opt/dq_framework/orchestration/local/run_pipeline.sh
```

## Verification

```sql
-- Every scheduler run shows up here, tagged by triggered_by
SELECT execution_id, run_type, status, triggered_by, started_at, ended_at, notes
  FROM monitoring.dq_execution_log
 ORDER BY execution_id DESC LIMIT 20;
```

Next step (8): Reporting & Power BI / Tableau scorecard + alerting module.
