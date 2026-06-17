#!/usr/bin/env python3
"""
assert_kpis.py
======================================================================
CI gate: queries reporting.v_executive_scorecard after the E2E demo
and fails the build if the framework regressed below thresholds.

Exit codes:
  0 = all KPIs within bounds
  1 = at least one KPI breached - build FAILS
"""
from __future__ import annotations
import argparse, os, sys
import psycopg2


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--min-pass-rate",     type=float, default=0.85)
    p.add_argument("--max-critical-fail", type=int,   default=0)
    p.add_argument("--max-duration-sec",  type=int,   default=300)
    args = p.parse_args()

    conn = psycopg2.connect(
        host=os.environ["PGHOST"], user=os.environ["PGUSER"],
        password=os.environ["PGPASSWORD"], dbname=os.environ["PGDATABASE"],
    )
    cur = conn.cursor()

    cur.execute("""
        SELECT overall_pass_rate,
               critical_failures,
               avg_pipeline_seconds
        FROM   reporting.v_executive_scorecard
    """)
    row = cur.fetchone()
    if row is None:
        print("FAIL :: scorecard returned no rows", file=sys.stderr)
        return 1

    pass_rate, critical_fail, duration = row
    failures = []

    if pass_rate < args.min_pass_rate:
        failures.append(f"pass_rate {pass_rate:.3f} < {args.min_pass_rate}")
    if critical_fail > args.max_critical_fail:
        failures.append(f"critical_failures {critical_fail} > {args.max_critical_fail}")
    if duration and duration > args.max_duration_sec:
        failures.append(f"avg_pipeline_seconds {duration} > {args.max_duration_sec}")

    if failures:
        print("KPI GATE FAILED:", file=sys.stderr)
        for f in failures:
            print(f"  - {f}", file=sys.stderr)
        return 1

    print(f"KPI gate OK :: pass_rate={pass_rate:.3f} critical={critical_fail} duration={duration}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
