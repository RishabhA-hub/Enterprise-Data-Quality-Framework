# Architecture Decision Records (ADRs)

## ADR-001: SQL-Based Rule Engine vs. Python DSL

### Status: Accepted

### Context
Rule authoring is the most frequent activity in the framework. We evaluated:
1. Pure Python DSL (custom classes/functions)
2. YAML-configured SQL templates
3. Native SQL with catalog metadata

### Decision
Use native SQL stored in the `rules` table with parameter substitution.

### Rationale
- **Performance**: SQL executes inside the database; no data movement.
- **Familiarity**: Data engineers already know SQL.
- **Auditability**: One language for rules, profiles, and reconciliations.
- **Versioning**: Git tracks schema migrations; rule SQL lives alongside.

### Consequences
- Positive: Sub-second execution on indexed columns; no serialization overhead.
- Positive: Rules can be tested directly in psql / DBeaver.
- Negative: Complex statistical operations require raw SQL (solved with helper functions).
- Negative: No IDE autocomplete for rule syntax (mitigated by validation in CI).

### Alternatives Considered
| Approach | Pros | Cons |
|---|---|---|
| Python DSL | Rich logic, libraries | Data movement, slower, learning curve |
| dbt tests | Community, macros | Tied to dbt ecosystem, less flexible |
| Great Expectations | Rich expectations, docs | Heavy dependency, Python-only |

---

## ADR-002: PostgreSQL as Primary Store vs. DuckDB/Snowflake

### Status: Accepted

### Context
The framework needs ACID transactions for rule executions, audit logging, and concurrent steward updates. We evaluated PostgreSQL, DuckDB, and cloud warehouses.

### Decision
PostgreSQL 16+ as the primary operational store.

### Rationale
- **ACID compliance**: Essential for audit log and quarantine state transitions.
- **JSONB**: Flexible metadata storage without schema migrations.
- **Extensions**: `pgcrypto`, `uuid-ossp`, `pg_stat_statements` built-in.
- **Cost**: Open source; runs anywhere (RDS, Cloud SQL, on-prem).
- **RLS**: Native row-level security for multi-tenant governance.

### Consequences
- Positive: Single database for rules, issues, audit, and scorecard.
- Positive: Excellent Terraform / IaC support.
- Negative: Analytical queries on >100M rows need indexing strategy (addressed with materialized views).
- Negative: Not a column store; aggregates are slower than DuckDB (acceptable for operational use).

### Alternatives Considered
| Approach | Pros | Cons |
|---|---|---|
| DuckDB | Fast analytics, embedded | No native RLS, no multi-user concurrency |
| Snowflake | Elastic scale | Cost, network latency, vendor lock-in |
| BigQuery | Serverless | Same as Snowflake + egress costs |

---

## ADR-003: In-Database Reconciliation vs. External Diff Tool

### Status: Accepted

### Context
ETL reconciliation requires comparing source and target record sets. Options: Python (pandas), CLI tool (diff), or SQL.

### Decision
SQL-based reconciliation using `FULL OUTER JOIN` and hash comparison.

### Rationale
- **Co-location**: Source and target often live in the same warehouse.
- **Scalability**: Database optimizes joins and aggregations.
- **Integration**: Results feed directly into `reconciliation_results` table.
- **Observability**: Execution time captured in `rule_executions` automatically.

### Consequences
- Positive: No external dependencies.
- Positive: Atomic transaction with other DQ checks.
- Negative: Complex nested JSON comparisons require helper functions (provided).
- Negative: Cross-database reconciliation requires FDW or export (documented pattern).

---

## ADR-004: Python + SQLAlchemy vs. Node.js/TypeScript for Engine

### Status: Accepted

### Context
The execution runner and profiler need a programming language. The web UI uses TypeScript.

### Decision
Python for the engine, TypeScript/React for the UI.

### Rationale
- **Data ecosystem**: Python has pandas, scipy, numpy for profiling.
- **SQL generation**: String templating is natural in Python.
- **Existing skills**: Data engineering teams are Python-first.
- **Separation**: Engine is backend service; UI is separate concern.

### Consequences
- Positive: Rapid development of statistical functions.
- Positive: Easy integration with ML models for anomaly detection (future).
- Negative: Two language ecosystems (mitigated by clear API boundary).
- Negative: Type safety across boundary requires discipline (addressed with Pydantic/Zod models).

---

## ADR-005: GitOps + Terraform vs. ClickOps

### Status: Accepted

### Context
Infrastructure and rule deployment need to be reproducible.

### Decision
All infrastructure in Terraform; rule schema changes in versioned SQL migrations.

### Rationale
- **Reproducibility**: `terraform apply` creates identical environments.
- **Review**: All changes in pull requests.
- **Rollback**: Terraform state + Git history enables rollback.
- **Compliance**: SOC-2 requires infrastructure as code.

### Consequences
- Positive: Disaster recovery is `terraform apply` + restore backup.
- Positive: No configuration drift.
- Negative: Learning curve for teams new to Terraform (addressed with documentation).
- Negative: Terraform state must be secured (stored in S3 with encryption + locking).

---

## ADR-006: OpenTelemetry vs. Vendor-Specific APM

### Status: Accepted

### Context
Observability needs traces, metrics, and logs. Vendors: Datadog, New Relic, AWS X-Ray, or open standard.

### Decision
OpenTelemetry with Prometheus/Grafana/Loki/Tempo.

### Rationale
- **Vendor-neutral**: Avoid lock-in; switch backends without code changes.
- **Cost**: Open source stack; pay for infrastructure only.
- **Standard**: Industry standard; broad language support.
- **Correlated**: Trace ID links logs, metrics, and traces.

### Consequences
- Positive: One instrumentation library for all signals.
- Positive: Cloud-native; runs on k8s or ECS.
- Negative: Self-hosted stack requires operational overhead (acceptable for enterprise).
- Negative: Alert routing to PagerDuty requires additional configuration (documented).

---

## ADR-007: Severity-Based Routing vs. All-Alerts-Equal

### Status: Accepted

### Context
When a rule fails, who gets notified and how urgently?

### Decision
4-tier severity with distinct routing:
- CRITICAL → Page on-call + Slack #data-incidents
- HIGH → Slack #data-alerts + email
- MEDIUM → Daily digest
- LOW → Weekly report

### Rationale
- **Alert fatigue**: Prevents desensitization.
- **SLA alignment**: Critical = 4h resolution per governance charter.
- **Cost**: PagerDuty incidents are expensive; reserve for true emergencies.

### Consequences
- Positive: Actionable signal-to-noise ratio.
- Negative: Requires accurate severity classification (enforced in rule catalog).

---

## ADR-008: Monorepo vs. Polyrepo

### Status: Accepted

### Context
12 steps produced SQL, Python, TypeScript, Terraform, and docs. How to structure?

### Decision
Single monorepo with directory structure by layer.

### Rationale
- **Atomic changes**: Rule SQL + engine code + test in one PR.
- **CI/CD**: Single pipeline validates everything.
- **Discovery**: New engineers find all artifacts in one place.

### Consequences
- Positive: Simpler dependency management.
- Positive: Unified versioning.
- Negative: Larger repo (mitigated by sparse checkouts if needed).
- Negative: More complex CI matrix (addressed with job partitioning).

---

## ADR-009: Row-Level Security vs. Application-Level Filtering

### Status: Accepted

### Context
Multi-tenant data access: should the app filter rows or the database?

### Decision
PostgreSQL RLS policies for all governance tables.

### Rationale
- **Tamper-proof**: Cannot be bypassed by app bug or SQL injection.
- **Performance**: Pushdown to query planner; efficient index usage.
- **Audit**: RLS is transparent; no application code to maintain.

### Consequences
- Positive: Security at the data layer.
- Positive: BI tools connecting directly respect policies.
- Negative: Complex policies can impact performance (mitigated with `security definer` functions).
- Negative: Debugging RLS requires `SET row_security = off` in admin sessions.

---

## ADR-010: Deterministic Demo Data vs. Live Production Data for Testing

### Status: Accepted

### Context
E2E tests need data. Options: production snapshot (anonymized) or synthetic data.

### Decision
Deterministic synthetic dataset with 9 known defect types.

### Rationale
- **Reproducibility**: `random.seed(42)` yields identical data every run.
- **Safety**: No risk of PII exposure.
- **Coverage**: Deliberately injects defects that real data may never exhibit.
- **CI-friendly**: Fast generation; no external dependencies.

### Consequences
- Positive: Regression tests are deterministic.
- Positive: New engineers understand defect taxonomy by examining data.
- Negative: Synthetic data may not capture all real-world edge cases (addressed with shadow testing in staging).

---

*All ADRs require approval from 2 senior engineers and the data architect. Amendments supersede prior versions.*
