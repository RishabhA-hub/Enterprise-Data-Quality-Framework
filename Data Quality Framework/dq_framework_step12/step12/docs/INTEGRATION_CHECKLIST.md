# Step 12: Integration Checklist

## Production Readiness Checklist

Before deploying the Data Quality Framework to production, verify every item below.

---

## Infrastructure

- [ ] PostgreSQL 16+ provisioned (RDS / Cloud SQL / self-managed)
- [ ] Multi-AZ enabled for production
- [ ] Automated backups configured (daily snapshots + PITR)
- [ ] Encryption at-rest enabled (KMS / cloud provider CMK)
- [ ] TLS 1.3 enforced for all connections
- [ ] VPC / Security Groups restrict access to application tier only
- [ ] S3 bucket for scorecards with Object Lock (7-year retention)
- [ ] Terraform state in S3 with encryption and locking
- [ ] CI/CD pipeline running and green (GitHub Actions)
- [ ] Container image built and scanned (trivy pass)

## Database

- [ ] All migrations applied successfully (`\dt` shows all tables)
- [ ] All GRANT statements executed for every table
- [ ] RLS enabled on governance tables (`rules`, `quarantine_issues`)
- [ ] Indexes created on high-cardinality filter columns
- [ ] `pgcrypto` and `uuid-ossp` extensions installed
- [ ] Connection pooling configured (PgBouncer or RDS Proxy)
- [ ] `max_connections` sized for expected concurrency
- [ ] Vacuum and autovacuum tuned for write-heavy tables

## Security

- [ ] 6 RBAC roles created and assigned (`30_rbac_roles.sql`)
- [ ] No `SUPERUSER` granted to application roles
- [ ] `bi_reader` can only access `reporting_masked` views
- [ ] Audit trigger installed on all governance tables
- [ ] `dq_audit_log` table has no `DELETE` or `UPDATE` grants
- [ ] Data classification tags applied to PII/PCI columns
- [ ] Masking functions tested: `fn_mask_email`, `fn_hash_id`
- [ ] Break-glass credentials stored in separate vault
- [ ] MFA enabled for `platform_admin` role
- [ ] Secrets rotated (no default passwords)

## Rules & Engine

- [ ] At least 1 rule per critical dataset
- [ ] All rules have valid SQL (tested in staging)
- [ ] Severity assigned correctly (CRITICAL = page on-call)
- [ ] Rule version history preserved (never UPDATE in-place)
- [ ] `is_active` flag used for soft-enable/disable
- [ ] ETL reconciliation mappings configured for all pipelines
- [ ] All 7 DAMA dimensions covered by at least 1 rule
- [ ] Statistical rules calibrated (Z-score threshold validated)
- [ ] Cross-table rules tested with realistic data

## Quarantine & Remediation

- [ ] Steward domains mapped (`dq_steward_domains` populated)
- [ ] All stewards have accounts and have logged in
- [ ] Notification channels tested (Slack / email)
- [ ] Quarantine SLA thresholds configured in alerting
- [ ] Bulk resolution procedures documented
- [ ] Reprocessing pipeline tested end-to-end

## Observability

- [ ] OpenTelemetry collector running
- [ ] Grafana dashboards imported and accessible
- [ ] Prometheus scraping application metrics
- [ ] Loki collecting application logs
- [ ] Tempo receiving distributed traces
- [ ] Alertmanager routing to PagerDuty (critical) and Slack (high)
- [ ] SLO dashboards show baseline (7-day window)
- [ ] `assert_kpis.py` passes in CI/CD

## Demo & Testing

- [ ] E2E demo runs successfully (`run_e2e_demo.sh`)
- [ ] All 9 defect types detected by at least 1 rule
- [ ] Integration tests pass in CI (GitHub Actions)
- [ ] Security scan passes (trivy + gitleaks)
- [ ] Load test completed (expected concurrency)
- [ ] Failover test completed (kill primary, verify replica promotion)

## Documentation

- [ ] `REFERENCE_ARCHITECTURE.md` reviewed by 2+ engineers
- [ ] `RUNBOOKS.md` printed / bookmarked by on-call
- [ ] `governance_charter.md` signed off by Legal/Compliance
- [ ] `QUICKSTART.md` tested by new hire (fresh machine)
- [ ] ADRs reviewed and archived
- [ ] Executive 1-pager distributed to leadership
- [ ] All runbooks have assigned owners and review dates

## Training & Rollout

- [ ] DQ Engineering team trained on rule authoring
- [ ] DQ Operators trained on pipeline execution
- [ ] Stewards trained on remediation UI
- [ ] BI team trained on masked reporting views
- [ ] Security team briefed on audit log location
- [ ] Executive team briefed on scorecard interpretation
- [ ] Pilot domain confirmed (2-week burn-in planned)

## Sign-Off

| Role | Name | Date | Signature |
|---|---|---|---|
| Data Platform Lead | | | |
| Data Engineering Manager | | | |
| Information Security | | | |
| Compliance / Legal | | | |
| Product Owner | | | |
| Site Reliability | | | |

---

*This checklist must be completed before production deployment. Incomplete items block the go-live decision.*
