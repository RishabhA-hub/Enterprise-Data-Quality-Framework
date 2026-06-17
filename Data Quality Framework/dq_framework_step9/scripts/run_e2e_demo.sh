#!/usr/bin/env bash
# ============================================================
# run_e2e_demo.sh
# One-shot end-to-end demo:
#   1. Apply core framework (Steps 1-8)
#   2. Generate + load demo data with intentional defects
#   3. Seed demo rules + recon pair
#   4. Run profiler, rule engine, ETL recon, quarantine, scorecard
#   5. Export reporting artifacts (CSV/XLSX/HTML)
# Designed to be runnable on a laptop in < 2 minutes.
# ============================================================
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
FRAMEWORK="${DQ_FRAMEWORK_ROOT:-$ROOT/../framework}"
LOG="$ROOT/run_$(date +%Y%m%d_%H%M%S).log"
exec > >(tee -a "$LOG") 2>&1

banner () { printf '\n============================================================\n%s\n============================================================\n' "$*"; }

banner "1. Schema bootstrap (core framework + demo)"
if [[ -d "$FRAMEWORK/sql" ]]; then
    for f in "$FRAMEWORK/sql"/*.sql; do
        echo "   applying $(basename "$f")"
        psql -v ON_ERROR_STOP=1 -f "$f"
    done
fi
psql -v ON_ERROR_STOP=1 -f "$ROOT/sql/20_demo_schema.sql"

banner "2. Generate synthetic data"
python3 "$ROOT/scripts/generate_demo_data.py"

banner "3. Load into demo_src + demo_tgt"
bash "$ROOT/scripts/load_demo.sh"

banner "4. Seed demo rules"
psql -v ON_ERROR_STOP=1 -f "$ROOT/sql/21_demo_rules.sql"

run_py () {
    local script="$1"; shift || true
    if [[ -f "$FRAMEWORK/$script" ]]; then
        echo ">> python3 $script $*"
        python3 "$FRAMEWORK/$script" "$@"
    else
        echo "!! missing $FRAMEWORK/$script -- skipping"
    fi
}

banner "5. Profiler"
run_py profiler.py --schema demo_src

banner "6. Rule engine"
run_py rule_engine.py --triggered-by demo

banner "7. ETL reconciliation"
run_py etl_recon.py

banner "8. Quarantine capture"
run_py quarantine_engine.py

banner "9. Scorecard + exports"
run_py scorecard.py
run_py scorecard_exporter.py --out "$ROOT/exports"

banner "10. Summary"
psql -v ON_ERROR_STOP=1 -c "
SELECT dimension,
       COUNT(*)                              AS rules_run,
       SUM(CASE WHEN status='PASS' THEN 1 ELSE 0 END) AS passed,
       SUM(CASE WHEN status='FAIL' THEN 1 ELSE 0 END) AS failed,
       SUM(failed_rows)                      AS failed_rows
FROM   dq_rule_results
WHERE  executed_at > now() - interval '10 minutes'
GROUP  BY dimension
ORDER  BY dimension;
"
psql -v ON_ERROR_STOP=1 -c "
SELECT status, COUNT(*) FROM quarantine.q_bad_rows GROUP BY status ORDER BY status;
"

banner "DONE  -- log: $LOG"
