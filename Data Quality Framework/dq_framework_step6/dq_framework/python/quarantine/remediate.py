"""
Remediation CLI — manage the lifecycle of quarantined rows.

Examples:
  python -m quarantine.remediate list --status OPEN --limit 20
  python -m quarantine.remediate assign 142 --to alice
  python -m quarantine.remediate fix    142 --note "email reformatted upstream"
  python -m quarantine.remediate reprocess 142
  python -m quarantine.remediate ignore  142 --note "test account, expected"
"""
from __future__ import annotations
import argparse
import sys
from .db import get_conn, dict_cursor


VALID_TRANSITIONS = {
    "assign":    ("IN_REVIEW",   "ASSIGNED"),
    "fix":       ("FIXED",       "FIXED"),
    "reprocess": ("REPROCESSED", "REPROCESSED"),
    "ignore":    ("IGNORED",     "IGNORED"),
    "reject":    ("REJECTED",    "REJECTED"),
}


def cmd_list(args):
    conn = get_conn()
    sql = """SELECT quarantine_id, schema_name, table_name, rule_code,
                    severity, status, business_key,
                    LEFT(failure_reason,60) AS reason,
                    quarantined_at
               FROM quarantine.q_bad_rows
              WHERE (%s IS NULL OR status = %s)
                AND (%s IS NULL OR severity = %s)
              ORDER BY quarantined_at DESC
              LIMIT %s"""
    with dict_cursor(conn) as cur:
        cur.execute(sql, (args.status, args.status,
                          args.severity, args.severity, args.limit))
        rows = cur.fetchall()
    for r in rows:
        print(f"#{r['quarantine_id']:>6}  {r['severity']:<8} {r['status']:<11} "
              f"{r['rule_code']:<8} {r['schema_name']}.{r['table_name']:<14} "
              f"bk={r['business_key']!s:<14} {r['reason']}")
    conn.close()


def cmd_transition(args, action: str):
    new_status, action_name = VALID_TRANSITIONS[action]
    conn = get_conn()
    with conn.cursor() as cur:
        cur.execute(
            """UPDATE quarantine.q_bad_rows
                  SET status=%s,
                      assigned_to=COALESCE(%s, assigned_to),
                      resolution_note=%s,
                      resolved_at = CASE WHEN %s IN ('FIXED','REPROCESSED','IGNORED','REJECTED')
                                         THEN NOW() ELSE resolved_at END
                WHERE quarantine_id=%s
                RETURNING status""",
            (new_status,
             getattr(args, "to", None),
             getattr(args, "note", None),
             new_status, args.quarantine_id))
        row = cur.fetchone()
    conn.commit()
    conn.close()
    if not row:
        print(f"quarantine_id={args.quarantine_id} not found")
        sys.exit(1)
    print(f"#{args.quarantine_id} -> {row[0]}  (action={action_name})")


def main():
    p = argparse.ArgumentParser(description="Quarantine Remediation CLI")
    sub = p.add_subparsers(dest="cmd", required=True)

    pl = sub.add_parser("list")
    pl.add_argument("--status", choices=["OPEN","IN_REVIEW","FIXED",
                                         "REPROCESSED","IGNORED","REJECTED"])
    pl.add_argument("--severity", choices=["LOW","MEDIUM","HIGH","CRITICAL"])
    pl.add_argument("--limit", type=int, default=50)
    pl.set_defaults(func=cmd_list)

    for action in ("assign","fix","reprocess","ignore","reject"):
        ap = sub.add_parser(action)
        ap.add_argument("quarantine_id", type=int)
        if action == "assign":
            ap.add_argument("--to", required=True)
        ap.add_argument("--note", default=None)
        ap.set_defaults(func=lambda a, _act=action: cmd_transition(a, _act))

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
