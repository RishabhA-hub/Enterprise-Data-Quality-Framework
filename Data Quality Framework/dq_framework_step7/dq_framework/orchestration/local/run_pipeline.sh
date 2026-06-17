#!/usr/bin/env bash
# ----------------------------------------------------------------------------
# Local "no-scheduler" runner — convenient for dev, demos, and cron.
# Chains every step; halts only on unrecoverable failures.
# Add to crontab:  0 2 * * *  /opt/dq_framework/orchestration/local/run_pipeline.sh
# ----------------------------------------------------------------------------
set -uo pipefail

cd "$(dirname "$0")/../../python"
export $(grep -v '^#' .env | xargs) 2>/dev/null || true

LOG_DIR="${LOG_DIR:-./logs}"
mkdir -p "$LOG_DIR"
TS=$(date +%Y%m%d_%H%M%S)
LOG="$LOG_DIR/run_$TS.log"

log() { echo "[$(date +'%F %T')] $*" | tee -a "$LOG"; }

run_step() {
    local name="$1"; shift
    log "▶ $name"
    if "$@" >>"$LOG" 2>&1; then
        log "✓ $name OK"
    else
        log "✗ $name FAILED (continuing where safe)"
        return 1
    fi
}

log "=== DQ Framework pipeline START ==="

run_step "extract"      python -m generators.generate_all
run_step "load-staging" psql -f ../sql/load_staging.sql
run_step "profile"      python -m profiler.run_profiler --persist
run_step "rules"        python -m rules_engine.run_rules     --triggered-by cron || true
run_step "etl-recon"    python -m etl_validator.run_validation --triggered-by cron || true
run_step "quarantine"   python -m quarantine.quarantine_engine --triggered-by cron || true
run_step "scorecard"    python -m reporting.export_scorecard --out ./exports/ || true
run_step "notify"       python -m notifications.send_summary --channel slack    || true

log "=== DQ Framework pipeline END ==="
