# Data Quality Framework — Reference Architecture

## Document Control
| | |
|---|---|
| Version | 1.0.0 |
| Status | Final |
| Owner | Data Platform Engineering |
| Review Cycle | Quarterly |

---

## 1. System Context

### 1.1 Purpose
This document defines the authoritative reference architecture for the Enterprise Data Quality (DQ) Framework. It serves as the single source of truth for:
- System component boundaries and interfaces
- Data flow topology
- Deployment topology across environments
- Integration patterns with upstream/downstream systems

### 1.2 Scope
In scope: Rule engine, profiling subsystem, quarantine pipeline, reconciliation engine, governance layer, observability stack, and CI/CD automation.
Out of scope: Source system OLTP schemas, BI tool internals, external data provider APIs.

---

## 2. Architectural Principles

| # | Principle | Rationale |
|---|---|---|
| 1 | **Schema-on-read validation** | Rules evaluate against existing schemas without forcing migrations. |
| 2 | **Shift-left quality** | Checks run in CI/CD before production deployment. |
| 3 | **Immutable audit trail** | All rule executions, changes, and access are append-only. |
| 4 | **Least-privilege access** | RBAC roles match job functions exactly. |
| 5 | **Fail-fast, quarantine-later** | Critical defects block pipelines; non-critical route to quarantine. |
| 6 | **Observability by default** | Every execution emits trace, metric, and log telemetry. |

---

## 3. Component Architecture

### 3.1 High-Level Topology

```
┌─────────────────────────────────────────────────────────────────────┐
│                        CLIENT LAYER                                  │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐                │
│  │  BI Tools   │  │  Data Eng   │  │  Steward UI │                │
│  │  (Read-Only)│  │  (Write)    │  │  (Remediation)│               │
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘                │
└─────────┼────────────────┼────────────────┼────────────────────────┘
          │                │                │
          ▼                ▼                ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      API / GATEWAY LAYER                             │
│         TanStack Server Functions  +  REST API Routes               │
│         Auth: JWT (Supabase Auth)  +  RBAC Middleware               │
└─────────────────────────────────────────────────────────────────────┘
          │
          ▼
┌─────────────────────────────────────────────────────────────────────┐
│                     DQ FRAMEWORK CORE                                │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌──────────┐ │
│  │ Rule Engine │  │  Profiler   │  │Reconciliation│  │Quarantine│ │
│  │  (SQL+Py)   │  │ (Stats+Meta)│  │  (ETL Diff)  │  │  (Hold)  │ │
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘  └─────┬────┘ │
│         │                │                │               │      │
│         └────────────────┴────────────────┘               │      │
│                          │                                │      │
│                          ▼                                ▼      │
│                   ┌─────────────┐                  ┌──────────┐  │
│                   │ v_scorecard │                  │dq_issues │  │
│                   │ (KPI View)  │                  │ (Action) │  │
│                   └─────────────┘                  └──────────┘  │
└─────────────────────────────────────────────────────────────────────┘
          │
          ▼
┌─────────────────────────────────────────────────────────────────────┐
│                     PERSISTENCE LAYER                                │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐               │
│  │  PostgreSQL │  │   S3 / GCS  │  │  Prometheus │               │
│  │  (Primary)  │  │ (Scorecards)│  │  (Metrics)  │               │
│  └─────────────┘  └─────────────┘  └─────────────┘               │
└─────────────────────────────────────────────────────────────────────┘
          │
          ▼
┌─────────────────────────────────────────────────────────────────────┐
│                     OBSERVABILITY LAYER                              │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌──────────┐  │
│  │   Grafana   │  │    Loki     │  │    Tempo    │  │  Alerts  │  │
│  │ (Dashboards)│  │   (Logs)    │  │  (Traces)   │  │(PagerDuty)│  │
│  └─────────────┘  └─────────────┘  └─────────────┘  └──────────┘  │
└─────────────────────────────────────────────────────────────────────┘
```

### 3.2 Component Catalog

#### Rule Engine
- **Purpose**: Executes declarative DQ rules against target datasets.
- **Interface**: `POST /api/dq/execute` (server function)
- **Dependencies**: PostgreSQL (rules catalog + execution logs)
- **Scale**: Horizontal via batch partitioning; single execution is OLTP-weight.

#### Profiler
- **Purpose**: Generates column-level statistics and inferred rules.
- **Interface**: `POST /api/dq/profile/{table}`
- **Output**: `profiling_results` table + inferred rule JSON.

#### Reconciliation Engine
- **Purpose**: Compares source ↔ target for ETL completeness/accuracy.
- **Interface**: `POST /api/dq/reconcile/{mapping_name}`
- **Key Feature**: Supports all 7 DAMA dimensions via configurable rule mapping.

#### Quarantine Pipeline
- **Purpose**: Isolates non-conforming records for manual remediation.
- **Interface**: `PATCH /api/dq/quarantine/{issue_id}`
- **Lifecycle**: Open → Under Review → Resolved → Reprocessed.

#### Governance Layer
- **Purpose**: RBAC, audit logging, data classification, and masked reporting.
- **Interface**: SQL views + server-side middleware.
- **Compliance**: SOX, SOC-2, GDPR artifact generation.

---

## 4. Data Flow

### 4.1 Standard Execution Flow

```
[Schedule / CI Trigger]
         │
         ▼
┌─────────────────┐
│  Load Ruleset   │ ──► ruleset_versions (lookup active rules)
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  Profile Data   │ ──► profiling_results (baseline stats)
└────────┬────────┘
         │
         ▼
┌─────────────────┐     ┌─────────────────┐
│  Execute Rules  │────►│ rule_executions │
└────────┬────────┘     └─────────────────┘
         │
    ┌────┴────┐
    │         │
    ▼         ▼
┌──────┐  ┌──────────┐
│ PASS │  │  FAIL    │ ──► quarantine_issues (create issue)
└──────┘  └──────────┘
              │
              ▼
    ┌─────────────────┐
    │  Scorecard KPIs  │ ──► v_executive_scorecard
    └─────────────────┘
```

### 4.2 Remediation Flow

```
[Steward UI]
    │
    ▼
┌─────────────────┐
│ Review Issue    │
└────────┬────────┘
         │
    ┌────┴────┐
    │         │
    ▼         ▼
┌──────┐  ┌──────────┐
│Reject│  │ Approve  │
│Close │  │  Fix     │
└──────┘  └────┬─────┘
               │
               ▼
        ┌─────────────┐
        │ Re-ingest   │ ──► Back to pipeline or mark resolved
        └─────────────┘
```

---

## 5. Deployment Architecture

### 5.1 Environment Topology

| Environment | Purpose | Data Sensitivity | Refresh |
|---|---|---|---|
| `dev` | Feature development | Synthetic | On commit |
| `staging` | Integration testing | Anonymized production | Daily |
| `prod` | Production execution | Live production | Real-time |

### 5.2 Infrastructure (AWS)

```
┌────────────────────────────────────────────┐
│                 VPC                        │
│  ┌──────────────────────────────────────┐  │
│  │           Public Subnet               │  │
│  │  [ALB] ──► [ECS / Fargate Tasks]      │  │
│  └──────────────────────────────────────┘  │
│  ┌──────────────────────────────────────┐  │
│  │           Private Subnet              │  │
│  │  [RDS PostgreSQL Multi-AZ]            │  │
│  │  [ElastiCache - optional]             │  │
│  └──────────────────────────────────────┘  │
│  ┌──────────────────────────────────────┐  │
│  │           VPC Endpoints               │  │
│  │  [S3 Gateway] [Secrets Manager]       │  │
│  └──────────────────────────────────────┘  │
└────────────────────────────────────────────┘
```

### 5.3 Secrets Management
- Application secrets: AWS Secrets Manager (rotation 90 days)
- Database credentials: RDS IAM Authentication where possible
- CI/CD secrets: GitHub Secrets + OIDC to AWS (no long-lived keys)

---

## 6. Integration Patterns

### 6.1 Upstream (Data Sources)
| System | Pattern | Frequency |
|---|---|---|
| OLTP Databases | Logical replication / CDC | Streaming |
| SaaS APIs | Scheduled batch extract | Hourly |
| Data Lake (S3) | S3 event notifications | Event-driven |
| Streaming (Kafka) | Consumer group | Streaming |

### 6.2 Downstream (Consumers)
| System | Pattern | Content |
|---|---|---|
| BI Tools (Tableau/Looker) | Read-only view | Masked scorecard |
| Data Catalog (Alation/Collibra) | API push | Rule metadata |
| Incident Management (PagerDuty) | Webhook | Critical alerts |
| Slack/Teams | Webhook | Daily digest |
| S3 Data Lake | Parquet export | Historical scorecards |

---

## 7. Performance & Scaling

### 7.1 Sizing Guidelines

| Dataset Size | Rule Count | Execution Time | Infrastructure |
|---|---|---|---|
| < 1M rows | < 50 | < 2 min | db.t3.medium |
| 1M - 10M | 50 - 200 | 2 - 10 min | db.r5.large |
| 10M - 100M | 200 - 500 | 10 - 30 min | db.r5.xlarge + partition |
| > 100M | > 500 | 30+ min | db.r5.2xlarge + parallel |

### 7.2 Scaling Mechanisms
- **Vertical**: RDS instance class upgrade (immediate)
- **Horizontal**: Partition by `data_domain` or `batch_id` (rule engine)
- **Caching**: Materialized views for scorecard queries (refresh 5 min)
- **Async**: Large reconciliations via background job queue

---

## 8. Security Architecture

### 8.1 Defense in Depth
```
Layer 1: Network (VPC, Security Groups, WAF)
Layer 2: Transport (TLS 1.3, cert pinning)
Layer 3: AuthN (JWT + MFA for admin)
Layer 4: AuthZ (RBAC + RLS)
Layer 5: Data (Encryption at-rest KMS, in-transit TLS)
Layer 6: Audit (Immutable log, SOC-2 artifacts)
```

### 8.2 Data Classification Handling
| Classification | Storage | Access | Masking |
|---|---|---|---|
| Public | Standard | All roles | None |
| Internal | Standard | Authenticated | None |
| Confidential | Encrypted | Role-restricted | Partial |
| Restricted (PII/PCI) | Encrypted + Tokenized | Need-to-know | Full mask/hash |

---

## 9. Disaster Recovery

### 9.1 RTO / RPO
| Scenario | RTO | RPO | Strategy |
|---|---|---|---|
| AZ failure | 5 min | 0 | Multi-AZ RDS (automatic) |
| Region failure | 30 min | 1 hour | Cross-region read replica promotion |
| Corrupt data | 1 hour | 24 hours | PITR (7-day window) |
| Full account compromise | 4 hours | 24 hours | Terraform rebuild + S3 backup restore |

### 9.2 Backup Strategy
- **Database**: Automated daily snapshots + 7-day PITR
- **Scorecards**: S3 Object Lock (7-year retention for compliance)
- **Rules/Config**: Git repository = source of truth; Terraform state in S3 with locking

---

## 10. Operational Interface Map

| Function | Interface | Role Required |
|---|---|---|
| View scorecard | BI Tool / Grafana | bi_reader |
| Author rules | SQL + Git | dq_engineer |
| Execute pipeline | CI/CD or API | dq_operator |
| Remediate issues | Steward UI | dq_steward |
| Manage roles | SQL + Terraform | platform_admin |
| Audit access | access_review.sh | platform_admin |

---

## Appendix A: Glossary

| Term | Definition |
|---|---|
| DAMA | Data Management Association — defines the 7 dimensions of data quality. |
| ETL Reconciliation | Comparison of source and target record sets for completeness. |
| Quarantine | Holding area for records that fail non-blocking rules. |
| RLS | Row-Level Security — PostgreSQL feature for policy-based access. |
| Shift-Left | Moving quality checks earlier in the development lifecycle. |

## Appendix B: Related Documents
- `governance_charter.md` — RACI, SLAs, break-glass
- `runbook_critical_failure.md` — Incident response
- `adr_001_sql_rules.md` — Why SQL over Python for rules
- `adr_002_postgres_vs_duckdb.md` — Storage engine choice
