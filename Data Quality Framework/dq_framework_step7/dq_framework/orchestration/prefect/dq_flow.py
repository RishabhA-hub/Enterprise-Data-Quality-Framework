"""
DQ Framework — Prefect 2.x equivalent of the Airflow DAG.

Run locally:   prefect deployment build dq_flow.py:dq_pipeline -n daily --cron "0 2 * * *"
"""
from __future__ import annotations

import subprocess
from prefect import flow, task, get_run_logger
from prefect.task_runners import SequentialTaskRunner


def _run(cmd: str) -> None:
    log = get_run_logger()
    log.info("$ %s", cmd)
    res = subprocess.run(cmd, shell=True, check=False, capture_output=True, text=True)
    log.info(res.stdout)
    if res.returncode != 0:
        log.error(res.stderr)
        raise RuntimeError(f"step failed ({res.returncode}): {cmd}")


@task(retries=2, retry_delay_seconds=300)
def extract():    _run("python -m generators.generate_all && psql -f ../sql/load_staging.sql")

@task(retries=1)
def profile():    _run("python -m profiler.run_profiler --persist")

@task(retries=1)
def rules():      _run("python -m rules_engine.run_rules --triggered-by prefect")

@task
def etl_recon():  _run("python -m etl_validator.run_validation --triggered-by prefect")

@task
def quarantine(): _run("python -m quarantine.quarantine_engine --triggered-by prefect")

@task
def scorecard():  _run("python -m reporting.export_scorecard --out ./exports/")

@task
def notify():     _run("python -m notifications.send_summary --channel slack")


@flow(name="dq-framework-daily", task_runner=SequentialTaskRunner())
def dq_pipeline():
    extract()
    profile()
    rules()
    etl_recon()
    quarantine()
    scorecard()
    notify()


if __name__ == "__main__":
    dq_pipeline()
