# Data Quality Governance Charter

> **Owner**: Chief Data Officer (CDO) — Office of the CDO
> **Version**: 1.0  •  **Effective**: 2026-Q2  •  **Review cadence**: Annual

---

## 1. Purpose

This charter codifies the operating model that governs the Data Quality (DQ)
Framework. It binds technology controls to **accountable humans** and aligns
with Fortune-500 reference frameworks: **DAMA-DMBOK 2**, **DCAM 2.2**,
**BCBS-239**, **ISO 8000-61** and **NIST Privacy Framework 1.0**.

---

## 2. RACI by activity

| Activity                              | Engineer | Operator | Steward | Owner (LOB) | CDO |
|---------------------------------------|:--------:|:--------:|:-------:|:-----------:|:---:|
| Author new DQ rule                    |   **R**  |    C     |    A    |      I      |  I  |
| Modify ETL reconciliation pair        |   **R**  |    I     |    C    |      I      |  I  |
| Approve rule severity = CRITICAL      |     C    |    I     |  **R**  |    **A**    |  I  |
| Promote rule from DEV → PROD          |     R    |    C     |    A    |      I      |  I  |
| Triage HIGH/CRITICAL alerts (24h SLA) |     C    |  **R**   |  **A**  |      I      |  I  |
| Sign off quarantine resolution        |     I    |    R     |  **A**  |      C      |  I  |
| Data classification (PII/PHI/SOX)     |     C    |    I     |  **R**  |    **A**    |  C  |
| Quarterly scorecard review            |     I    |    I     |    C    |      R      | **A** |
| Break-glass production hotfix         |   **R**  |    I     |    C    |      I      | **A** |

R = Responsible · A = Accountable · C = Consulted · I = Informed

---

## 3. Role definitions (mapped to DB roles in `30_rbac_roles.sql`)

| Charter role     | DB role          | Typical headcount | Mandate                                                                 |
|------------------|------------------|-------------------|-------------------------------------------------------------------------|
| Platform Admin   | `platform_admin` | 2 (break-glass)   | DDL, role grants, secret rotation. MFA + JIT access required.           |
| DQ Engineer      | `dq_engineer`    | 4–8               | Author/maintain rules, recon pairs, profiling jobs.                     |
| DQ Operator      | `dq_operator`    | Service + 2 SREs  | Run pipelines, manage quarantine workflow, page on-call.                |
| Data Steward     | `dq_steward`     | 1 per data domain | Domain ownership, severity sign-off, remediation approval.              |
| BI Reader        | `bi_reader`      | All analysts      | Read-only on `reporting.*` and `reporting_masked.*`. No raw access.     |
| App Runtime      | `app_runtime`    | 1 service account | Used by Airflow/Prefect. RLS bypass via `SET row_security = off`.       |

---

## 4. SLAs and severity ladder

| Severity   | Detection → Notify | Acknowledge | Remediate | Escalation if breached       |
|------------|--------------------|-------------|-----------|------------------------------|
| CRITICAL   | ≤ 5 min            | ≤ 15 min    | ≤ 4 h     | PagerDuty → Steward → CDO    |
| HIGH       | ≤ 15 min           | ≤ 1 h       | ≤ 24 h    | Slack #dq-alerts → Steward   |
| MEDIUM     | ≤ 1 h              | ≤ 1 BD      | ≤ 5 BD    | Email digest → Engineer      |
| LOW        | Daily digest       | Best effort | Backlog   | None                         |

BD = business day. SLAs are enforced by `reporting.v_active_alerts` +
the alerting module (Step 8).

---

## 5. Change management

1. All rule changes flow through Git PRs against `dq_meta/rules/*.sql`.
2. CI runs the **rule_engine** in DEV against a frozen golden dataset.
3. A Steward approves PRs that raise severity to HIGH/CRITICAL.
4. Production deploys are immutable, tagged releases (`vYYYY.MM.DD`).
5. Every change is auto-captured in `dq_meta.dq_audit_log` (Step 10).

---

## 6. Audit & compliance

* **Append-only** audit table; UPDATE/DELETE revoked from non-admins.
* Retention: **7 years** (SOX). Quarterly export to immutable object storage (WORM).
* Quarterly access reviews against `pg_roles` and `dq_steward_domains`.
* Annual penetration test of the reporting layer and BI connections.

---

## 7. Exceptions & break-glass

Break-glass access to `platform_admin` requires:
1. Documented incident ticket (Sev-1 or Sev-2).
2. MFA + just-in-time grant (≤ 4 h TTL).
3. Post-incident review entered into `dq_meta.dq_audit_log` within 48 h.
