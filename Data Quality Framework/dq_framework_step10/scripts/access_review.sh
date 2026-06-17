#!/usr/bin/env bash
# =====================================================================
# access_review.sh
# Generates a quarterly access-review CSV for SOX / SOC 2 auditors.
# Outputs:
#   - role_membership.csv       (who belongs to which group role)
#   - object_privileges.csv     (effective grants on dq_meta + reporting)
#   - steward_domain_map.csv    (RLS scope per steward)
#   - audit_activity_90d.csv    (top users by audit-log volume)
# =====================================================================
set -euo pipefail

OUT_DIR="${1:-./access_review_$(date +%Y%m%d)}"
mkdir -p "$OUT_DIR"

run_q() {
  local name="$1" sql="$2"
  echo "[*] $name"
  psql -v ON_ERROR_STOP=1 -A -F"," --pset=footer=off -c "COPY ($sql) TO STDOUT WITH CSV HEADER" \
       > "$OUT_DIR/${name}.csv"
}

run_q "role_membership" "
  SELECT r.rolname AS group_role,
         m.rolname AS member,
         m.rolcanlogin AS can_login
  FROM pg_auth_members am
  JOIN pg_roles r ON r.oid = am.roleid
  JOIN pg_roles m ON m.oid = am.member
  WHERE r.rolname IN ('platform_admin','dq_engineer','dq_operator',
                      'dq_steward','bi_reader','app_runtime')
  ORDER BY group_role, member
"

run_q "object_privileges" "
  SELECT grantee, table_schema, table_name, string_agg(privilege_type, ',' ORDER BY privilege_type) AS privs
  FROM information_schema.role_table_grants
  WHERE table_schema IN ('dq_meta','reporting','reporting_masked')
    AND grantee NOT IN ('postgres','PUBLIC')
  GROUP BY grantee, table_schema, table_name
  ORDER BY grantee, table_schema, table_name
"

run_q "steward_domain_map" "
  SELECT db_user, data_domain, granted_at, granted_by
  FROM dq_meta.dq_steward_domains
  ORDER BY db_user, data_domain
"

run_q "audit_activity_90d" "
  SELECT db_user,
         schema_name||'.'||table_name AS object,
         action,
         count(*) AS events,
         min(event_time) AS first_event,
         max(event_time) AS last_event
  FROM dq_meta.dq_audit_log
  WHERE event_time >= now() - interval '90 days'
  GROUP BY db_user, object, action
  ORDER BY events DESC
"

echo "[OK] Access-review package written to $OUT_DIR"
