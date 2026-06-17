"""
DQ Framework — Daily Orchestration DAG (Airflow 2.x)
=====================================================
End-to-end pipeline:

    extract  ──►  profile  ──►  rules  ──►  etl_recon  ──►  quarantine
                                   │                              │
                                   └──────────► scorecard ◄───────┘
                                                    │
                                                    ▼
                                                  notify

- Each step calls the framework's existing Python modules via BashOperator,
  so the DAG stays a thin scheduling layer (no business logic duplicated).
- Failures in `rules` or `etl_recon` are NON-blocking (trigger_rule='all_done')
  so quarantine + scorecard still run and bad data is captured.
- SLA: full pipeline must finish in 60 min; per-task SLAs sized for prod load.
- Secrets (PGHOST/PGPASSWORD) injected from Airflow connection `dq_postgres`.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from airflow import DAG
from airflow.operators.bash import BashOperator
from airflow.operators.empty import EmptyOperator
from airflow.utils.trigger_rule import TriggerRule


default_args = {
    "owner":            "data-quality",
    "depends_on_past":  False,
    "retries":          2,
    "retry_delay":      timedelta(minutes=5),
    "email_on_failure": True,
    "email":            ["dq-alerts@company.com"],
    "sla":              timedelta(minutes=20),
}

ENV = (
    "export PGHOST={{ conn.dq_postgres.host }} "
    "PGPORT={{ conn.dq_postgres.port }} "
    "PGDATABASE={{ conn.dq_postgres.schema }} "
    "PGUSER={{ conn.dq_postgres.login }} "
    "PGPASSWORD={{ conn.dq_postgres.password }} && "
    "cd /opt/dq_framework/python && "
)

with DAG(
    dag_id="dq_framework_daily",
    description="Enterprise DQ pipeline: profile → rules → ETL recon → quarantine → scorecard",
    default_args=default_args,
    start_date=datetime(2025, 1, 1),
    schedule_interval="0 2 * * *",     # 02:00 UTC daily
    catchup=False,
    max_active_runs=1,
    tags=["data-quality", "etl", "monitoring"],
    sla_miss_callback=None,             # plug in PagerDuty/Slack callback here
) as dag:

    start = EmptyOperator(task_id="start")

    extract = BashOperator(
        task_id="extract_to_staging",
        bash_command=ENV + "python -m generators.generate_all && "
                           "psql -f ../sql/load_staging.sql",
        doc_md="Generates synthetic source data and bulk-loads staging.* tables.",
    )

    profile = BashOperator(
        task_id="profile_staging",
        bash_command=ENV + "python -m profiler.run_profiler --persist",
        doc_md="Profiles every staging table; writes monitoring.dq_profile_results.",
    )

    rules = BashOperator(
        task_id="run_dq_rules",
        bash_command=ENV + "python -m rules_engine.run_rules --triggered-by airflow",
        trigger_rule=TriggerRule.ALL_SUCCESS,
        doc_md="Executes metadata-driven rules; writes dq_rule_results + dq_quality_scores.",
    )

    etl_recon = BashOperator(
        task_id="etl_reconciliation",
        bash_command=ENV + "python -m etl_validator.run_validation --triggered-by airflow",
        trigger_rule=TriggerRule.ALL_DONE,    # run even if rules had failures
        doc_md="Staging↔clean reconciliation (row counts, sums, distincts, orphans).",
    )

    quarantine = BashOperator(
        task_id="quarantine_bad_rows",
        bash_command=ENV + "python -m quarantine.quarantine_engine --triggered-by airflow",
        trigger_rule=TriggerRule.ALL_DONE,
        doc_md="Snapshots violating rows into quarantine.q_bad_rows for stewardship.",
    )

    scorecard = BashOperator(
        task_id="publish_scorecard",
        bash_command=ENV + "python -m reporting.export_scorecard --out /opt/dq_framework/exports/",
        trigger_rule=TriggerRule.ALL_DONE,
        doc_md="Exports overall + per-dimension DQ scores to CSV/Parquet for BI.",
    )

    notify = BashOperator(
        task_id="notify_stakeholders",
        bash_command=ENV + "python -m notifications.send_summary --channel slack",
        trigger_rule=TriggerRule.ALL_DONE,
        doc_md="Posts run summary + SLA breaches to Slack/Teams/email.",
    )

    end = EmptyOperator(task_id="end", trigger_rule=TriggerRule.ALL_DONE)

    start >> extract >> profile >> rules
    rules >> [etl_recon, quarantine] >> scorecard >> notify >> end
