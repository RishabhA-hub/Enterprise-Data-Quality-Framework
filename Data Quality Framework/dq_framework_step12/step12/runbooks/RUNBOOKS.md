# Operational Runbook Collection

## Runbook Index
| ID | Scenario | Severity | Response Time |
|---|---|---|---|
| RB-001 | Critical Rule Failure Spike | P1 | 15 min |
| RB-002 | Reconciliation Gap Detected | P1 | 30 min |
| RB-003 | Quarantine Backlog Overflow | P2 | 1 hour |
| RB-004 | Rule Execution Performance Degradation | P2 | 1 hour |
| RB-005 | Database Connection Exhaustion | P1 | 15 min |
| RB-006 | False Positive Alert Storm | P3 | 4 hours |
| RB-007 | Steward Assignment Failure | P3 | 4 hours |
| RB-008 | Audit Log Export Failure | P2 | 2 hours |
| RB-009 | CI/CD Pipeline Blockage | P2 | 1 hour |
| RB-010 | Security Incident (Unauthorized Access) | P0 | Immediate |

---

## RB-001: Critical Rule Failure Spike

### Symptoms
- PagerDuty alert: `CRITICAL failures > threshold`
- Grafana panel: `dq.rule_failures{severity="CRITICAL"}` spiking
- Scorecard: Pass rate drops below 85%

### Immediate Response (0-15 min)
1. Acknowledge PagerDuty incident.
2. Open Grafana dashboard: `DQ Executive Scorecard`
3. Identify failing rule(s) from alert metadata:
   ```sql
   SELECT rule_name, failed_count, error_message
   FROM rule_executions
   WHERE execution_time > NOW() - INTERVAL '1 hour'
     AND severity = 'CRITICAL'
     AND status = 'FAILED'
   ORDER BY failed_count DESC;
   ```
4. Determine scope:
   - Single rule? → Likely rule logic or source schema change.
   - Multiple rules on same table? → Likely upstream data incident.
   - Across all tables? → Infrastructure issue (DB, network).

### Investigation (15-30 min)
**If single rule failure:**
```sql
-- Get sample failing records
SELECT * FROM quarantine_issues
WHERE rule_id = '<failing_rule_id>'
  AND created_at > NOW() - INTERVAL '1 hour'
LIMIT 10;
```
- Check if source data changed (new column values, schema drift).
- Check if rule threshold is too strict (recent trend analysis).

**If upstream data incident:**
- Contact data producer team via #data-incidents Slack channel.
- Check CDC lag: `SELECT * FROM pg_stat_replication;`

**If infrastructure issue:**
- Check RDS metrics: CPU, connections, disk I/O.
- Check application logs in Loki for connection errors.

### Resolution (30 min - 2 hours)
| Cause | Fix | Verification |
|---|---|---|
| Rule too strict | Adjust threshold + version rule | Re-run rule, confirm pass |
| Schema drift | Update rule SQL or add migration | CI/CD tests pass |
| Bad source data | Coordinate upstream fix + manual quarantine | Source data profile normal |
| DB overload | Scale RDS or stagger execution | CPU < 80%, latency < 2 min |

### Communication
- Slack #data-incidents: Initial assessment within 15 min.
- Status page update if > 1 hour.
- Post-incident review if > 4 hours or customer impact.

---

## RB-002: Reconciliation Gap Detected

### Symptoms
- Alert: `reconciliation.status = GAP_DETECTED`
- Scorecard: `completeness_score < 100%`

### Immediate Response
1. Identify the mapping:
   ```sql
   SELECT mapping_name, source_query, target_query, gap_count
   FROM reconciliation_results
   WHERE status = 'GAP_DETECTED'
   ORDER BY checked_at DESC
   LIMIT 1;
   ```
2. Get gap details:
   ```sql
   SELECT * FROM reconciliation_results
   WHERE mapping_name = '<name>'
     AND status = 'GAP_DETECTED'
   ORDER BY checked_at DESC;
   ```

### Common Causes
| Cause | Signature | Fix |
|---|---|---|
| ETL job failed | Gap count = large batch size | Restart ETL, backfill |
| Filter mismatch | Source has records target excludes | Align WHERE clauses |
| Late-arriving data | Gap resolves on next run | Tune reconciliation schedule |
| Orphan records | Source deleted, target preserved | Implement soft-delete sync |

### Verification
```sql
-- Re-run reconciliation manually
SELECT * FROM fn_reconcile('<mapping_name>');
-- Confirm status = CONSISTENT
```

---

## RB-003: Quarantine Backlog Overflow

### Symptoms
- Grafana: `dq.quarantine_open_count` > 1000 and growing
- SLA alert: Open issues older than threshold

### Response
1. Identify backlog composition:
   ```sql
   SELECT data_domain, severity, COUNT(*) as cnt,
          AVG(EXTRACT(EPOCH FROM (NOW() - created_at))/3600) as avg_age_hours
   FROM quarantine_issues
   WHERE status = 'OPEN'
   GROUP BY data_domain, severity
   ORDER BY cnt DESC;
   ```
2. If single domain: Reassign additional stewards or escalate domain owner.
3. If systemic:
   - Check steward assignment automation:
     ```sql
     SELECT * FROM dq_steward_domains WHERE domain = '<domain>';
     ```
   - If unassigned, run auto-assignment fix.
   - If assigned but inactive, escalate to manager.

### Bulk Resolution (Emergency)
For known false positives:
```sql
-- Mark category as resolved with comment
UPDATE quarantine_issues
SET status = 'RESOLVED',
    resolution = 'BULK: False positive due to <reason>',
    resolved_at = NOW(),
    resolved_by = '<operator_id>'
WHERE rule_id = '<rule_id>'
  AND status = 'OPEN'
  AND created_at < NOW() - INTERVAL '7 days';
```
**Requires platform_admin or dq_steward role.**

---

## RB-004: Rule Execution Performance Degradation

### Symptoms
- Grafana: `dq.rule.duration_ms` p99 > 5 minutes
- CI/CD pipeline timing out

### Diagnosis
1. Identify slow rules:
   ```sql
   SELECT rule_name, AVG(duration_ms) as avg_ms, MAX(duration_ms) as max_ms
   FROM rule_executions
   WHERE execution_time > NOW() - INTERVAL '24 hours'
   GROUP BY rule_name
   ORDER BY avg_ms DESC
   LIMIT 10;
   ```
2. Check execution plan:
   ```sql
   EXPLAIN ANALYZE <rule_sql>;
   ```

### Fixes
| Problem | Solution |
|---|---|
| Missing index on filter column | Add index (coordinate with DBA) |
| Full table scan on large table | Add partition predicate or rewrite rule |
| Complex JOIN | Denormalize or use materialized view |
| Concurrent execution conflict | Stagger schedule or use advisory locks |

---

## RB-005: Database Connection Exhaustion

### Symptoms
- App errors: `FATAL: sorry, too many clients already`
- RDS metric: `DatabaseConnections` at limit

### Response
1. Check current connections:
   ```sql
   SELECT usename, state, COUNT(*) FROM pg_stat_activity
   GROUP BY usename, state;
   ```
2. Kill idle connections > 10 minutes (emergency):
   ```sql
   SELECT pg_terminate_backend(pid)
   FROM pg_stat_activity
   WHERE state = 'idle'
     AND NOW() - state_change > INTERVAL '10 minutes'
     AND usename NOT IN ('rdsadmin', 'postgres');
   ```
3. Increase `max_connections` in RDS parameter group (requires reboot).
4. Implement connection pooling (PgBouncer) for long-term fix.

---

## RB-006: False Positive Alert Storm

### Symptoms
- Hundreds of non-actionable alerts in short window.
- Pass rate artificially low due to overly strict rule.

### Response
1. Identify the offending rule(s).
2. Temporarily disable (dq_operator):
   ```sql
   UPDATE rules
   SET is_active = FALSE, updated_at = NOW()
   WHERE rule_id = '<rule_id>';
   ```
3. Adjust threshold or add exclusion clause.
4. Re-enable and monitor.

---

## RB-007: Steward Assignment Failure

### Symptoms
- Quarantine issues created but `assigned_to` is NULL.
- Steward not receiving notifications.

### Response
1. Check steward mapping:
   ```sql
   SELECT * FROM dq_steward_domains
   WHERE domain = '<affected_domain>';
   ```
2. If missing, add mapping:
   ```sql
   INSERT INTO dq_steward_domains (domain, steward_user_id, steward_email)
   VALUES ('<domain>', '<user_uuid>', '<email>');
   ```
3. If steward left company, update mapping and reassign open issues.

---

## RB-008: Audit Log Export Failure

### Symptoms
- `access_review.sh` or SOC-2 automation fails.
- S3 upload errors.

### Response
1. Check S3 bucket permissions and Object Lock status.
2. Verify IAM role has `s3:PutObject`.
3. If local disk full, clear temp files:
   ```bash
   rm -f /tmp/audit_export_*.csv
   ```
4. Manual fallback:
   ```sql
   \copy (SELECT * FROM dq_audit_log WHERE created_at > NOW() - INTERVAL '30 days') TO '/tmp/audit_manual.csv' CSV HEADER;
   ```

---

## RB-009: CI/CD Pipeline Blockage

### Symptoms
- GitHub Actions failing at `assert_kpis.py`.
- Build blocked from merge.

### Response
1. Check failure reason in Actions log.
2. If KPI gate failed:
   - Review `v_executive_scorecard` in staging.
   - If staging data is bad (expected), temporarily lower gate:
     ```yaml
     # In workflow file (emergency only)
     python assert_kpis.py --min-pass-rate 0.75 --max-critical-fail 5
     ```
   - Create ticket to fix root cause.
3. If security scan failed (trivy/gitleaks):
   - Do NOT bypass. Fix vulnerability first.

---

## RB-010: Security Incident (Unauthorized Access)

### Severity: P0 — Immediate Response Required

### Response
1. **Contain**: Revoke suspect sessions:
   ```sql
   -- If using Supabase Auth, revoke via API or admin panel
   -- Rotate affected credentials immediately
   ```
2. **Investigate**: Query audit log:
   ```sql
   SELECT * FROM dq_audit_log
   WHERE table_name IN ('rules', 'quarantine_issues', 'user_roles')
     AND action IN ('INSERT', 'UPDATE', 'DELETE')
     AND created_at > NOW() - INTERVAL '1 hour'
   ORDER BY created_at DESC;
   ```
3. **Assess**: Determine data exposure scope.
4. **Notify**: Security team, Legal (if PII involved), CISO.
5. **Remediate**: Force password reset, enable MFA, patch vulnerability.
6. **Document**: Post-incident report within 24 hours.

---

## Runbook Maintenance
- Review all runbooks quarterly or after every P0/P1 incident.
- Update procedures in the same PR as the code fix.
- Drill exercises: Simulate RB-001 monthly in staging.
