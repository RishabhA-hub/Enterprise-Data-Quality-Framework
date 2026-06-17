"""
ETL Validation & Source-to-Target Reconciliation
------------------------------------------------
Verifies the staging -> clean ETL preserved the data correctly:

  CHECKS
    1. row_count       — source rows == target rows (+ rejected)
    2. sum_check       — SUM(numeric measure) matches within tolerance
    3. distinct_check  — DISTINCT(business key) cardinality matches
    4. hash_check      — MD5 row-hash sample matches (configurable %)
    5. null_check      — NULL counts on key cols match source
    6. orphan_check    — FK columns in target resolve to dim PKs

Every check writes one row to monitoring.etl_validation_results.
Reads its job catalog from monitoring.etl_validation_jobs (seeded SQL).

Fortune-500 framing:
- Reconciliation is *mandatory* in regulated industries (SOX, BCBS-239)
- Tolerance-based comparisons (not strict equality) to allow for
  controlled transformations (e.g. currency rounding)
- Every reconciliation tied to an execution_id for full audit trail
"""
from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import dataclass, field
from typing import Optional

from .db import get_conn, dict_cursor

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(message)s",
)
log = logging.getLogger("etl_validator")


@dataclass
class CheckResult:
    job_id: int
    job_name: str
    check_type: str
    source_value: Optional[float]
    target_value: Optional[float]
    diff: Optional[float]
    diff_pct: Optional[float]
    tolerance_pct: float
    status: str             # PASS / WARN / FAIL / ERROR
    detail: str = ""


# ---------------------------------------------------------------------------
# Execution header (reuse monitoring.dq_execution_log)
# ---------------------------------------------------------------------------
def open_execution(conn, triggered_by: str = "cli") -> int:
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO monitoring.dq_execution_log
                   (run_type, status, started_at, triggered_by)
               VALUES ('ETL_RECON','RUNNING', NOW(), %s)
               RETURNING execution_id""",
            (triggered_by,),
        )
        eid = cur.fetchone()[0]
    conn.commit()
    return eid


def close_execution(conn, eid: int, status: str, notes: str = "") -> None:
    with conn.cursor() as cur:
        cur.execute(
            """UPDATE monitoring.dq_execution_log
                  SET status=%s, ended_at=NOW(), notes=%s
                WHERE execution_id=%s""",
            (status, notes, eid),
        )
    conn.commit()


# ---------------------------------------------------------------------------
# Scalar fetch helper
# ---------------------------------------------------------------------------
def fetch_scalar(conn, sql: str) -> Optional[float]:
    with conn.cursor() as cur:
        cur.execute(sql)
        row = cur.fetchone()
    if not row or row[0] is None:
        return None
    return float(row[0])


# ---------------------------------------------------------------------------
# Individual check executors
# ---------------------------------------------------------------------------
def _compare(src: Optional[float], tgt: Optional[float],
             tolerance_pct: float) -> tuple[Optional[float], Optional[float], str]:
    if src is None or tgt is None:
        return None, None, "ERROR"
    diff = tgt - src
    base = abs(src) if abs(src) > 0 else 1.0
    diff_pct = round(abs(diff) / base * 100.0, 6)
    if diff_pct == 0:
        status = "PASS"
    elif diff_pct <= tolerance_pct:
        status = "WARN"
    else:
        status = "FAIL"
    return diff, diff_pct, status


def run_check(conn, job: dict) -> CheckResult:
    tol = float(job.get("tolerance_pct") or 0.0)
    src_sql = job["source_sql"]
    tgt_sql = job["target_sql"]
    name = job["job_name"]
    ctype = job["check_type"]
    try:
        src_val = fetch_scalar(conn, src_sql)
        tgt_val = fetch_scalar(conn, tgt_sql)
    except Exception as e:
        conn.rollback()
        return CheckResult(
            job_id=job["job_id"], job_name=name, check_type=ctype,
            source_value=None, target_value=None,
            diff=None, diff_pct=None,
            tolerance_pct=tol, status="ERROR", detail=str(e),
        )

    diff, diff_pct, status = _compare(src_val, tgt_val, tol)
    return CheckResult(
        job_id=job["job_id"], job_name=name, check_type=ctype,
        source_value=src_val, target_value=tgt_val,
        diff=diff, diff_pct=diff_pct,
        tolerance_pct=tol, status=status,
    )


def persist(conn, execution_id: int, r: CheckResult) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO monitoring.etl_validation_results
                  (execution_id, job_id, job_name, check_type,
                   source_value, target_value, diff, diff_pct,
                   tolerance_pct, status, detail, executed_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s, NOW())""",
            (execution_id, r.job_id, r.job_name, r.check_type,
             r.source_value, r.target_value, r.diff, r.diff_pct,
             r.tolerance_pct, r.status, r.detail),
        )
    conn.commit()


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------
def fetch_jobs(conn, job_filter: Optional[str] = None):
    sql = """SELECT job_id, job_name, check_type, source_sql, target_sql,
                    tolerance_pct, is_active
               FROM monitoring.etl_validation_jobs
              WHERE is_active = TRUE"""
    params = []
    if job_filter:
        sql += " AND job_name = %s"
        params.append(job_filter)
    sql += " ORDER BY job_id"
    with dict_cursor(conn) as cur:
        cur.execute(sql, params)
        return cur.fetchall()


def run(job_filter: Optional[str] = None, triggered_by: str = "cli") -> int:
    conn = get_conn()
    eid = open_execution(conn, triggered_by)
    fails = errs = 0
    overall = "SUCCESS"
    try:
        jobs = fetch_jobs(conn, job_filter)
        log.info("Loaded %d ETL validation jobs", len(jobs))

        for job in jobs:
            r = run_check(conn, job)
            persist(conn, eid, r)
            log.info("[%s] %-30s %s  src=%s tgt=%s diff_pct=%s",
                     r.status, r.job_name, r.check_type,
                     r.source_value, r.target_value, r.diff_pct)
            if r.status == "FAIL":
                fails += 1
            elif r.status == "ERROR":
                errs += 1

        if errs:
            overall = "FAILED"
        elif fails:
            overall = "COMPLETED_WITH_FAILURES"

        close_execution(conn, eid, overall,
                        f"jobs={len(jobs)} fail={fails} error={errs}")
    except Exception as e:
        log.exception("Validator crashed: %s", e)
        close_execution(conn, eid, "FAILED", str(e))
        raise
    finally:
        conn.close()
    return eid


def main():
    p = argparse.ArgumentParser(description="ETL Source-to-Target Reconciliation")
    p.add_argument("--job", help="Only run a specific job_name")
    p.add_argument("--triggered-by", default="cli")
    args = p.parse_args()
    eid = run(args.job, args.triggered_by)
    print(f"\nETL validation complete. execution_id={eid}")
    print("Inspect with:")
    print(f"  SELECT * FROM monitoring.etl_validation_results WHERE execution_id={eid};")


if __name__ == "__main__":
    sys.exit(main())
