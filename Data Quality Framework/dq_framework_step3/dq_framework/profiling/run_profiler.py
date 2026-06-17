"""
CLI: profile every staging table and optionally persist results.

Usage:
    python run_profiler.py                       # profile all stg_* tables, print
    python run_profiler.py --persist             # also INSERT into monitoring
    python run_profiler.py --table stg_customer  # single table
    python run_profiler.py --out profile.csv     # export CSV
"""
from __future__ import annotations

import argparse
from datetime import datetime

import pandas as pd

from db import cursor
from profiler import profile_table, persist_profile


def list_staging_tables() -> list[str]:
    with cursor() as cur:
        cur.execute("""
            SELECT table_name FROM information_schema.tables
            WHERE table_schema = 'staging' AND table_name LIKE 'stg_%'
            ORDER BY table_name
        """)
        return [r["table_name"] for r in cur.fetchall()]


def open_execution(name: str) -> int:
    with cursor(commit=True) as cur:
        cur.execute("""
            INSERT INTO monitoring.dq_execution_log (run_name, run_type, started_at, status)
            VALUES (%s, 'PROFILE', %s, 'RUNNING')
            RETURNING execution_id
        """, (name, datetime.utcnow()))
        return cur.fetchone()["execution_id"]


def close_execution(execution_id: int, status: str = "SUCCESS") -> None:
    with cursor(commit=True) as cur:
        cur.execute("""
            UPDATE monitoring.dq_execution_log
            SET ended_at = %s, status = %s
            WHERE execution_id = %s
        """, (datetime.utcnow(), status, execution_id))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--table", help="Specific staging table (e.g. stg_customer)")
    ap.add_argument("--persist", action="store_true", help="Write to monitoring")
    ap.add_argument("--out", help="Write profile DataFrame to CSV path")
    args = ap.parse_args()

    tables = [args.table] if args.table else list_staging_tables()
    if not tables:
        print("No staging tables found.")
        return

    exec_id = open_execution("profile_run") if args.persist else None
    frames: list[pd.DataFrame] = []
    try:
        for t in tables:
            print(f"-> profiling staging.{t}")
            df = profile_table("staging", t)
            frames.append(df)
            print(df[["column_name", "inferred_type", "row_count",
                      "null_pct", "distinct_pct"]].to_string(index=False))
            if exec_id is not None:
                persist_profile(df, exec_id)
        if exec_id is not None:
            close_execution(exec_id, "SUCCESS")
    except Exception as e:
        if exec_id is not None:
            close_execution(exec_id, "FAILED")
        raise

    if args.out and frames:
        pd.concat(frames, ignore_index=True).to_csv(args.out, index=False)
        print(f"\nWrote {args.out}")


if __name__ == "__main__":
    main()
