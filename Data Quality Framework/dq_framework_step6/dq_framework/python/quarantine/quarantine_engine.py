"""
Quarantine Engine
-----------------
For each failing rule from monitoring.dq_rules, re-run a "selector" query
to fetch the actual violating rows, snapshot each as JSONB, and INSERT
into quarantine.q_bad_rows.

Convention: dq_rules.rule_sql counts violations (used in Step 4).
A second metadata column dq_rules.selector_sql returns the FULL violating rows.
If selector_sql is NULL, we auto-derive it from rule_sql by replacing
the SELECT list with SELECT *.

Severity mapping comes from dq_rules.severity directly.
"""
from __future__ import annotations
import argparse
import logging
import re
import sys
from typing import Optional
from psycopg2.extras import Json
from .db import get_conn, dict_cursor

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s | %(levelname)-7s | %(message)s")
log = logging.getLogger("quarantine")


# ---------------------------------------------------------------------------
# Schema bootstrap — ensure dq_rules has selector_sql column
# ---------------------------------------------------------------------------
def ensure_selector_column(conn):
    with conn.cursor() as cur:
        cur.execute("""
            ALTER TABLE monitoring.dq_rules
              ADD COLUMN IF NOT EXISTS selector_sql TEXT
        """)
    conn.commit()


# ---------------------------------------------------------------------------
# Execution header
# ---------------------------------------------------------------------------
def open_execution(conn, triggered_by="cli") -> int:
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO monitoring.dq_execution_log
                   (run_type, status, started_at, triggered_by)
               VALUES ('QUARANTINE','RUNNING', NOW(), %s)
               RETURNING execution_id""",
            (triggered_by,))
        eid = cur.fetchone()[0]
    conn.commit()
    return eid


def close_execution(conn, eid, status, notes=""):
    with conn.cursor() as cur:
        cur.execute("""UPDATE monitoring.dq_execution_log
                          SET status=%s, ended_at=NOW(), notes=%s
                        WHERE execution_id=%s""",
                    (status, notes, eid))
    conn.commit()


# ---------------------------------------------------------------------------
# Selector derivation
# ---------------------------------------------------------------------------
COUNT_PATTERN = re.compile(r"SELECT\s+COUNT\s*\(.*?\)", re.IGNORECASE | re.DOTALL)


def derive_selector(rule_sql: str) -> Optional[str]:
    """Replace 'SELECT COUNT(*)' with 'SELECT *' so we get the bad rows."""
    if not COUNT_PATTERN.search(rule_sql):
        return None
    return COUNT_PATTERN.sub("SELECT *", rule_sql, count=1) + " LIMIT 10000"


# ---------------------------------------------------------------------------
# Per-rule quarantine
# ---------------------------------------------------------------------------
def quarantine_rule(conn, rule: dict, eid: int) -> int:
    rule_sql = rule["rule_sql"]
    selector = rule.get("selector_sql") or derive_selector(rule_sql)
    if not selector:
        log.warning("Skip %s — no selector_sql and rule_sql is not a COUNT(*) pattern",
                    rule["rule_code"])
        return 0

    schema, table = rule["schema_name"], rule["table_name"]
    bk_col = rule.get("business_key_column") or _guess_bk(table)

    try:
        with dict_cursor(conn) as cur:
            cur.execute(selector)
            bad_rows = cur.fetchall()
    except Exception as e:
        conn.rollback()
        log.error("Selector failed for %s: %s", rule["rule_code"], e)
        return 0

    if not bad_rows:
        return 0

    with conn.cursor() as cur:
        for row in bad_rows:
            payload = {k: _json_safe(v) for k, v in row.items()}
            cur.execute(
                """INSERT INTO quarantine.q_bad_rows
                       (execution_id, rule_id, rule_code, schema_name, table_name,
                        business_key, payload, failure_reason, severity)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (eid, rule["rule_id"], rule["rule_code"], schema, table,
                 str(payload.get(bk_col)) if bk_col in payload else None,
                 Json(payload),
                 f"{rule['rule_code']} — {rule['rule_name']}",
                 rule["severity"]))
    conn.commit()
    log.info("Quarantined %d rows for %s (%s.%s)",
             len(bad_rows), rule["rule_code"], schema, table)
    return len(bad_rows)


def _guess_bk(table: str) -> str:
    if table.endswith("customer"): return "customer_id"
    if table.endswith("employee"): return "employee_id"
    if table.endswith("sales"):    return "order_id"
    return "id"


def _json_safe(v):
    """Convert non-JSON-serializable values (Decimal, datetime, bytes) to str."""
    if v is None or isinstance(v, (str, int, float, bool, dict, list)):
        return v
    return str(v)


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------
def fetch_failed_rules(conn, source_execution_id: Optional[int]):
    """Pick rules that produced violations in a given (or latest) RULES run."""
    if source_execution_id is None:
        with conn.cursor() as cur:
            cur.execute("""SELECT MAX(execution_id) FROM monitoring.dq_execution_log
                            WHERE run_type='RULES'""")
            source_execution_id = cur.fetchone()[0]
    if source_execution_id is None:
        return [], None

    with dict_cursor(conn) as cur:
        cur.execute("""
            SELECT r.rule_id, r.rule_code, r.rule_name, r.schema_name, r.table_name,
                   r.column_name, r.dimension, r.severity, r.rule_sql, r.selector_sql,
                   res.violation_count
              FROM monitoring.dq_rule_results res
              JOIN monitoring.dq_rules        r ON r.rule_id = res.rule_id
             WHERE res.execution_id = %s
               AND res.violation_count > 0
             ORDER BY res.violation_count DESC
        """, (source_execution_id,))
        return cur.fetchall(), source_execution_id


def run(source_execution_id: Optional[int] = None, triggered_by="cli") -> int:
    conn = get_conn()
    ensure_selector_column(conn)
    eid = open_execution(conn, triggered_by)
    total = 0
    try:
        rules, src_eid = fetch_failed_rules(conn, source_execution_id)
        log.info("Quarantine sourcing from RULES execution_id=%s (%d failing rules)",
                 src_eid, len(rules))
        for r in rules:
            total += quarantine_rule(conn, r, eid)
        close_execution(conn, eid, "SUCCESS",
                        f"source_run={src_eid} rules={len(rules)} quarantined={total}")
    except Exception as e:
        log.exception("Quarantine engine crashed: %s", e)
        close_execution(conn, eid, "FAILED", str(e))
        raise
    finally:
        conn.close()
    log.info("Quarantine complete — %d rows captured (execution_id=%s)", total, eid)
    return eid


def main():
    p = argparse.ArgumentParser(description="DQ Quarantine Engine")
    p.add_argument("--from-execution", type=int,
                   help="Source RULES execution_id (default: latest)")
    p.add_argument("--triggered-by", default="cli")
    args = p.parse_args()
    eid = run(args.from_execution, args.triggered_by)
    print(f"\nQuarantine complete. execution_id={eid}")
    print("Inspect:")
    print(f"  SELECT * FROM quarantine.q_bad_rows WHERE execution_id={eid} LIMIT 20;")
    print( "  SELECT * FROM quarantine.v_open_by_table;")


if __name__ == "__main__":
    sys.exit(main())
