"""
Rule Execution Engine
---------------------
Metadata-driven DQ rule runner. Reads rules from monitoring.dq_rules,
executes each rule's `rule_sql` (which MUST return a single integer:
the number of violating rows), and persists results to
monitoring.dq_rule_results. Rolls up per-table dimension scores into
monitoring.dq_quality_scores.

Design principles (Fortune-500 grade):
- Metadata-driven: zero code changes to add a new rule -> just INSERT a row
- Idempotent per execution_id (one run header per invocation)
- Quarantine-friendly: violating row counts captured, optional sample export
- Dimension rollups: completeness, validity, uniqueness, consistency,
  accuracy, timeliness — weighted average becomes overall quality score
"""
from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from .db import get_conn, dict_cursor

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(message)s",
)
log = logging.getLogger("rules_engine")


# Default dimension weights (must sum to 1.0). Override via CLI if needed.
DEFAULT_DIM_WEIGHTS = {
    "completeness": 0.25,
    "validity":     0.20,
    "uniqueness":   0.15,
    "consistency":  0.15,
    "accuracy":     0.15,
    "timeliness":   0.10,
}


@dataclass
class RuleResult:
    rule_id: int
    rule_code: str
    schema_name: str
    table_name: str
    column_name: Optional[str]
    dimension: str
    severity: str
    total_rows: int
    violations: int
    pass_rate_pct: float
    status: str          # PASS / WARN / FAIL / ERROR
    error_msg: Optional[str] = None


# ---------------------------------------------------------------------------
# Execution header
# ---------------------------------------------------------------------------
def open_execution(conn, run_type: str = "RULES", triggered_by: str = "cli") -> int:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO monitoring.dq_execution_log
                (run_type, status, started_at, triggered_by)
            VALUES (%s, 'RUNNING', NOW(), %s)
            RETURNING execution_id
            """,
            (run_type, triggered_by),
        )
        eid = cur.fetchone()[0]
    conn.commit()
    log.info("Opened execution_id=%s (run_type=%s)", eid, run_type)
    return eid


def close_execution(conn, execution_id: int, status: str, notes: str = "") -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE monitoring.dq_execution_log
               SET status = %s,
                   ended_at = NOW(),
                   notes = %s
             WHERE execution_id = %s
            """,
            (status, notes, execution_id),
        )
    conn.commit()
    log.info("Closed execution_id=%s status=%s", execution_id, status)


# ---------------------------------------------------------------------------
# Rule execution
# ---------------------------------------------------------------------------
def fetch_active_rules(conn, table_filter: Optional[str] = None):
    sql = """
        SELECT rule_id, rule_code, rule_name, schema_name, table_name,
               column_name, dimension, severity, rule_sql, threshold_pct
          FROM monitoring.dq_rules
         WHERE is_active = TRUE
    """
    params = []
    if table_filter:
        sql += " AND table_name = %s"
        params.append(table_filter)
    sql += " ORDER BY rule_id"
    with dict_cursor(conn) as cur:
        cur.execute(sql, params)
        return cur.fetchall()


def count_table_rows(conn, schema: str, table: str) -> int:
    with conn.cursor() as cur:
        cur.execute(f'SELECT COUNT(*) FROM "{schema}"."{table}"')
        return cur.fetchone()[0]


def execute_rule(conn, rule: dict, execution_id: int) -> RuleResult:
    schema = rule["schema_name"]
    table = rule["table_name"]
    threshold = float(rule.get("threshold_pct") or 100.0)

    try:
        total = count_table_rows(conn, schema, table)
    except Exception as e:
        return RuleResult(
            rule_id=rule["rule_id"], rule_code=rule["rule_code"],
            schema_name=schema, table_name=table,
            column_name=rule.get("column_name"),
            dimension=rule["dimension"], severity=rule["severity"],
            total_rows=0, violations=0, pass_rate_pct=0.0,
            status="ERROR", error_msg=f"count failed: {e}",
        )

    try:
        with conn.cursor() as cur:
            cur.execute(rule["rule_sql"])
            row = cur.fetchone()
            violations = int(row[0]) if row and row[0] is not None else 0
    except Exception as e:
        conn.rollback()
        return RuleResult(
            rule_id=rule["rule_id"], rule_code=rule["rule_code"],
            schema_name=schema, table_name=table,
            column_name=rule.get("column_name"),
            dimension=rule["dimension"], severity=rule["severity"],
            total_rows=total, violations=0, pass_rate_pct=0.0,
            status="ERROR", error_msg=str(e),
        )

    pass_rate = 100.0 if total == 0 else round((total - violations) * 100.0 / total, 4)
    if pass_rate >= threshold:
        status = "PASS"
    elif pass_rate >= threshold - 5:
        status = "WARN"
    else:
        status = "FAIL"

    return RuleResult(
        rule_id=rule["rule_id"], rule_code=rule["rule_code"],
        schema_name=schema, table_name=table,
        column_name=rule.get("column_name"),
        dimension=rule["dimension"], severity=rule["severity"],
        total_rows=total, violations=violations,
        pass_rate_pct=pass_rate, status=status,
    )


def persist_result(conn, execution_id: int, r: RuleResult) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO monitoring.dq_rule_results
                (execution_id, rule_id, schema_name, table_name, column_name,
                 dimension, severity, total_rows, violation_count,
                 status, error_msg, executed_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s, NOW())
            """,
            (execution_id, r.rule_id, r.schema_name, r.table_name, r.column_name,
             r.dimension, r.severity, r.total_rows, r.violations,
             r.status, r.error_msg),
        )
    conn.commit()


# ---------------------------------------------------------------------------
# Dimension rollup
# ---------------------------------------------------------------------------
def rollup_scores(conn, execution_id: int, weights: dict) -> None:
    """
    Aggregate pass-rates per (table, dimension) for this execution
    and write monitoring.dq_quality_scores.
    """
    with dict_cursor(conn) as cur:
        cur.execute(
            """
            SELECT schema_name, table_name, dimension,
                   AVG(pass_rate_pct)::numeric(7,4) AS dim_score,
                   COUNT(*)              AS rules_run,
                   SUM(violation_count)  AS total_violations
              FROM monitoring.dq_rule_results
             WHERE execution_id = %s
             GROUP BY schema_name, table_name, dimension
            """,
            (execution_id,),
        )
        rows = cur.fetchall()

    # group by table -> dimension dict
    by_table: dict[tuple[str, str], dict] = {}
    for row in rows:
        key = (row["schema_name"], row["table_name"])
        by_table.setdefault(key, {"dims": {}, "violations": 0, "rules": 0})
        by_table[key]["dims"][row["dimension"]] = float(row["dim_score"])
        by_table[key]["violations"] += int(row["total_violations"] or 0)
        by_table[key]["rules"] += int(row["rules_run"])

    with conn.cursor() as cur:
        for (schema, table), agg in by_table.items():
            dims = agg["dims"]
            # weighted overall score (only dims present contribute; renormalize)
            present = {d: weights[d] for d in dims if d in weights}
            w_sum = sum(present.values()) or 1.0
            overall = sum(dims[d] * (present.get(d, 0) / w_sum) for d in dims)

            cur.execute(
                """
                INSERT INTO monitoring.dq_quality_scores
                    (execution_id, schema_name, table_name,
                     completeness_score, validity_score, uniqueness_score,
                     consistency_score, accuracy_score, timeliness_score,
                     overall_score, total_rules_run, total_violations,
                     scored_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s, NOW())
                """,
                (
                    execution_id, schema, table,
                    dims.get("completeness"), dims.get("validity"),
                    dims.get("uniqueness"),   dims.get("consistency"),
                    dims.get("accuracy"),     dims.get("timeliness"),
                    round(overall, 4), agg["rules"], agg["violations"],
                ),
            )
    conn.commit()
    log.info("Wrote %d quality-score rows for execution_id=%s",
             len(by_table), execution_id)


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------
def run(table_filter: Optional[str] = None,
        triggered_by: str = "cli") -> int:
    conn = get_conn()
    execution_id = open_execution(conn, "RULES", triggered_by)
    overall_status = "SUCCESS"
    fail_count = 0
    error_count = 0

    try:
        rules = fetch_active_rules(conn, table_filter)
        log.info("Loaded %d active rules", len(rules))

        for rule in rules:
            r = execute_rule(conn, rule, execution_id)
            persist_result(conn, execution_id, r)
            tag = f"[{r.status}]"
            log.info("%-6s %s  %s.%s  viol=%d/%d  pass=%.2f%%",
                     tag, r.rule_code, r.schema_name, r.table_name,
                     r.violations, r.total_rows, r.pass_rate_pct)
            if r.status == "FAIL":
                fail_count += 1
            elif r.status == "ERROR":
                error_count += 1

        rollup_scores(conn, execution_id, DEFAULT_DIM_WEIGHTS)

        if error_count:
            overall_status = "FAILED"
        elif fail_count:
            overall_status = "COMPLETED_WITH_FAILURES"

        close_execution(
            conn, execution_id, overall_status,
            f"rules={len(rules)} fail={fail_count} error={error_count}",
        )
    except Exception as e:
        log.exception("Engine crashed: %s", e)
        close_execution(conn, execution_id, "FAILED", str(e))
        raise
    finally:
        conn.close()

    return execution_id


def main():
    p = argparse.ArgumentParser(description="DQ Rule Execution Engine")
    p.add_argument("--table", help="Only run rules for this staging table")
    p.add_argument("--triggered-by", default="cli")
    args = p.parse_args()
    eid = run(args.table, args.triggered_by)
    print(f"\nExecution complete. execution_id={eid}")
    print("Inspect with:")
    print(f"  SELECT * FROM monitoring.dq_rule_results   WHERE execution_id={eid};")
    print(f"  SELECT * FROM monitoring.dq_quality_scores WHERE execution_id={eid};")


if __name__ == "__main__":
    sys.exit(main())
