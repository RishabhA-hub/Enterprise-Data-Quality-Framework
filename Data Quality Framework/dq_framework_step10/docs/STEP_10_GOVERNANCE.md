# Step 10 — Governance, RBAC & Audit Hardening

This step transforms the DQ framework from a *working pipeline* into an
**auditable, Fortune-500-grade control plane**. It introduces formal
roles, append-only auditing, data classification, BI-safe masked views,
and row-level multi-tenant segregation.

---

## What ships in this package

| File                                  | Purpose                                                |
|---------------------------------------|--------------------------------------------------------|
| `sql/30_rbac_roles.sql`               | Six least-privilege group roles + future-proof grants  |
| `sql/31_audit_log.sql`                | Append-only `dq_audit_log` + generic trigger function  |
| `sql/32_data_classification.sql`      | PII/PHI/PCI/SOX catalog + coverage gap view            |
| `sql/33_masked_views.sql`             | `reporting_masked.*` views with PARTIAL/HASH/REDACT    |
| `sql/34_rls_policies.sql`             | Row-Level Security per `data_domain`                   |
| `policies/governance_charter.md`      | RACI, SLAs, change-management, break-glass policy      |
| `scripts/access_review.sh`            | Quarterly SOX/SOC-2 access-review extractor            |

---

## Apply order (idempotent)

```bash
psql -f sql/30_rbac_roles.sql
psql -f sql/31_audit_log.sql
psql -f sql/32_data_classification.sql
psql -f sql/33_masked_views.sql
psql -f sql/34_rls_policies.sql
```

All scripts are wrapped in `BEGIN/COMMIT` and use `IF NOT EXISTS` /
`DO $$ ... $$` guards, so they may be re-applied safely (CI-friendly).

---

## Role model (mirrors `governance_charter.md` §3)

```text
              ┌──────────────────┐
              │  platform_admin  │  (break-glass, MFA + JIT)
              └────────┬─────────┘
                       │ owns DDL
        ┌──────────────┼──────────────┐
        │              │              │
 dq_engineer     dq_operator     dq_steward
 (authors rules) (runs jobs)     (signs off)
        │              │              │
        └────────┬─────┴──────┬───────┘
                 │            │
            app_runtime    bi_reader
            (Airflow svc) (Tableau/PBI/Looker)
```

* `bi_reader` has SELECT **only** on `reporting.*` and
  `reporting_masked.*` — never on raw tables.
* `app_runtime` inherits `dq_operator` and bypasses RLS via
  `ALTER ROLE app_runtime SET row_security = off`.

---

## Auditability

* Every INSERT/UPDATE/DELETE on `dq_rules`, `dq_etl_recon_pairs`, and
  `dq_quarantine` is captured in `dq_meta.dq_audit_log` with:
  `db_user`, `client_addr`, `application_name`, `old_row`, `new_row`,
  and a `changed_cols TEXT[]` diff.
* Audit log is **append-only**: `REVOKE UPDATE, DELETE FROM PUBLIC`.
* Trigger function runs `SECURITY DEFINER` with locked
  `search_path = dq_meta, pg_temp` (prevents search_path hijacks).

---

## Data classification & masking

`dq_data_classification` tags every sensitive column with a
**sensitivity level**, a **masking strategy**, and **regulatory tags**
(`GDPR`, `CCPA`, `HIPAA`, `SOX`, …).

The companion view `reporting.v_classification_coverage` flags
`UNCLASSIFIED` columns so the steward can close governance gaps.

`reporting_masked.*` views apply masking at query time:

| Strategy   | Function                 | Example                            |
|------------|--------------------------|------------------------------------|
| PARTIAL    | `fn_mask_partial`        | `Johnathan` → `Jo*****an`          |
| EMAIL      | `fn_mask_email`          | `j.doe@acme.com` → `j***@acme.com` |
| HASH       | `fn_hash_id` (SHA-256)   | `42` → `73475cb40a568...`          |

BI tools should be pointed at `reporting_masked.*`, never raw schemas.

---

## Row-Level Security (multi-domain)

* `dq_rules` and `dq_quarantine` gain a `data_domain TEXT` column
  (default `GLOBAL`).
* `dq_steward_domains` maps each steward DB user to the domains they own.
* `fn_has_domain_access(p_domain)` is `SECURITY DEFINER`, `STABLE`, and
  short-circuits for engineers / platform admins.
* Policies use `FORCE ROW LEVEL SECURITY` so even table owners are
  scoped (defense-in-depth).

To grant a new steward access to the `FINANCE` domain:

```sql
INSERT INTO dq_meta.dq_steward_domains(db_user, data_domain)
VALUES ('jane.steward','FINANCE');
```

---

## Quarterly access review

```bash
PGHOST=... PGUSER=... PGPASSWORD=... ./scripts/access_review.sh \
    /mnt/audit/2026Q2
```

Produces four CSVs ready to hand to internal audit / SOC-2 assessors:

1. `role_membership.csv`
2. `object_privileges.csv`
3. `steward_domain_map.csv`
4. `audit_activity_90d.csv`

---

## Verification queries

```sql
-- 1. Confirm bi_reader cannot see raw PII
SET ROLE bi_reader;
SELECT * FROM demo_src.customers LIMIT 1;  -- expect: permission denied
SELECT * FROM reporting_masked.customers LIMIT 1;  -- expect: masked rows
RESET ROLE;

-- 2. Confirm audit trigger fires
UPDATE dq_meta.dq_rules SET severity = severity WHERE rule_id = 1;
SELECT action, db_user, changed_cols
FROM dq_meta.dq_audit_log ORDER BY audit_id DESC LIMIT 5;

-- 3. Confirm RLS scopes a steward
SET ROLE jane.steward;
SELECT data_domain, count(*) FROM dq_meta.dq_rules GROUP BY 1;
RESET ROLE;

-- 4. Find unclassified sensitive columns
SELECT * FROM reporting.v_classification_coverage
WHERE coverage_status = 'UNCLASSIFIED';
```

---

## What's next — Step 11 preview

**Step 11 — CI/CD, IaC & Observability**: GitHub Actions pipeline that
lints SQL (sqlfluff), runs the rule engine against a Dockerised Postgres
on every PR, publishes Terraform modules for the schema + Airflow
connections, and ships an OpenTelemetry exporter that pushes pipeline
metrics to Prometheus/Datadog.

Reply **`next`** to generate Step 11.
