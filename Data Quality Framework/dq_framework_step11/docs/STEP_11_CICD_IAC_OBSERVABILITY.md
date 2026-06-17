# Step 11 — CI/CD, Infrastructure-as-Code & Observability

This step wraps the framework in the production-grade scaffolding a
Fortune-500 platform team expects: automated linting + testing,
reproducible cloud infrastructure, container delivery, and end-to-end
observability with SLO-based alerting.

---

## Deliverables

| File                                                  | Purpose                                               |
|-------------------------------------------------------|-------------------------------------------------------|
| `ci/github-actions-dq-ci.yml`                         | 5-stage pipeline: lint → unit → integration → security → publish |
| `ci/.sqlfluff`                                        | Postgres-dialect SQL style enforcement                 |
| `ci/.pre-commit-config.yaml`                          | Local + CI pre-commit hooks (sqlfluff, ruff, gitleaks) |
| `ci/Dockerfile`                                       | Multi-stage, non-root runner image with tini PID-1     |
| `terraform/main.tf`                                   | RDS + KMS + Secrets Manager + S3 (WORM) + CloudWatch   |
| `terraform/envs/prd.tfvars`                           | Per-environment input variables                        |
| `observability/otel_instrumentation.py`               | Python OTEL bootstrap + 5 standard metrics             |
| `observability/otel-collector-config.yaml`            | Collector fan-out to Prometheus / Tempo / Loki / Datadog |
| `observability/grafana-dashboard-dq-executive.json`   | Importable executive dashboard                         |
| `observability/prometheus-alerts.yaml`                | 5 SLO-based PromQL alerts                              |
| `scripts/assert_kpis.py`                              | CI quality gate vs `v_executive_scorecard`             |

---

## CI pipeline (`github-actions-dq-ci.yml`)

```text
 ┌──────┐   ┌──────┐   ┌─────────────┐   ┌─────────┐   ┌─────────┐
 │ lint │──▶│ unit │──▶│ integration │──▶│ security│──▶│ publish │
 └──────┘   └──────┘   └─────────────┘   └─────────┘   └─────────┘
                              │
                         Postgres 16
                         service container
                       + scripts/run_e2e_demo.sh
                       + scripts/assert_kpis.py
```

* **Integration job** spins a real Postgres 16 service container, applies
  every migration in `sql/*.sql` lexicographically, runs the Step-9 E2E
  demo, then enforces KPI thresholds:
  `pass_rate ≥ 0.85`, `critical_failures = 0`, `avg_pipeline ≤ 300s`.
* **Security job** runs `trivy fs` (HIGH/CRITICAL) and `gitleaks`.
  Both must pass before publish.
* **Publish job** is gated on `main` only and pushes an OCI image
  to `ghcr.io/<repo>/dq-runner:{latest,$sha}` with GHA cache.

---

## Container image (`ci/Dockerfile`)

* Multi-stage build (`builder` → `runtime`), ~120 MB final image.
* Runs as **non-root** UID 10001 (`dq`).
* PID-1 = `tini` for clean signal propagation under
  KubernetesPodOperator.
* `HEALTHCHECK` returns non-zero if the `engine` package fails to import,
  letting k8s and Docker Swarm replace stuck pods.
* OTEL endpoint, service name, and protocol baked in as env defaults.

---

## Terraform module (`terraform/main.tf`)

A single root module provisions everything required to **run** the
framework in AWS. Key controls:

| Resource         | Hardening choice                                            |
|------------------|-------------------------------------------------------------|
| RDS Postgres 16  | Multi-AZ in prd, `storage_encrypted=true`, KMS CMK, IAM auth, 35-day backups |
| Secrets Manager  | KMS-encrypted, 7-day recovery window, JSON payload          |
| S3 exports       | Object Lock + versioning + KMS + public-access block + 7-year lifecycle |
| KMS              | Customer-managed key with **rotation enabled**              |
| CloudWatch       | Encrypted log group + metric filter pattern matching `severity=CRITICAL && event=sla_breach` |
| State backend    | `backend "s3" {}` configured via `-backend-config` in CI    |

Deploy:

```bash
cd terraform
terraform init -backend-config=envs/prd.backend.hcl
terraform apply -var-file=envs/prd.tfvars
```

---

## OpenTelemetry

### Standard metrics emitted by the pipeline

| Metric                      | Type                | Purpose                          |
|-----------------------------|---------------------|----------------------------------|
| `dq.rules.executed`         | Counter             | Volume / throughput              |
| `dq.rule.duration_ms`       | Histogram           | Latency SLO + Grafana percentiles |
| `dq.rule.pass_rate`         | Observable Gauge    | Live KPI per data domain         |
| `dq.recon.gap_rows`         | Counter             | ETL recon drift                  |
| `dq.sla.breaches`           | Counter             | Pages / on-call signal           |

### Collector fan-out

```text
   dq-runner pods
        │ OTLP/HTTP :4318
        ▼
 ┌──────────────────┐
 │ otel-collector   │
 ├──────────────────┤
 │ memory_limiter   │
 │ attr/redact (PII)│
 │ batch            │
 └──┬──────┬──────┬─┘
    │      │      │
 Prometheus Tempo  Loki      (and Datadog if DD_API_KEY set)
   :9464   :4317  :3100
```

The `attributes/redact` processor strips `db.statement.parameters` and
`http.request.header.authorization` **before** export — protects PII
from leaking into trace backends.

---

## Alerting (Prometheus rules)

| Alert                          | Threshold                              | Severity |
|--------------------------------|----------------------------------------|----------|
| `DQPipelineDurationHigh`       | P95 rule duration > 10 min for 15m     | warning  |
| `DQCriticalRuleFailing`        | Any CRITICAL rule fails                | critical (pages) |
| `DQReconciliationGap`          | > 1k recon gap rows / 15m              | high     |
| `DQPipelineMissingHeartbeat`   | No executions for 30 min               | critical (pages) |
| `DQSlaBreachSurge`             | > 5 SLA breaches / hour                | high     |

`page: "true"` routes through Alertmanager → PagerDuty (matches the
`pagerduty` alerting channel from Step 8).

---

## Local developer workflow

```bash
# One-time
pip install pre-commit && pre-commit install --config ci/.pre-commit-config.yaml

# Per change
git commit -m "feat: add new rule"     # hooks auto-run sqlfluff, ruff, gitleaks
gh pr create                            # CI runs the full 5-stage pipeline
```

---

## Verification checklist

* [ ] PR opens → `lint`, `unit`, `integration`, `security` jobs all green
* [ ] `terraform plan` produces no drift after merge
* [ ] Container image appears at `ghcr.io/<repo>/dq-runner:<sha>`
* [ ] Grafana dashboard imports cleanly and shows live data
* [ ] Triggering a CRITICAL rule failure pages within 5 min via PagerDuty

---

## What's next — Step 12 preview

**Step 12 — Capstone: Reference Architecture & Runbooks**: a single
package that stitches Steps 1–11 into a polished reference architecture
deliverable — C4 diagrams, on-call runbooks, DR plan, cost model,
maturity-assessment scorecard, and an executive 1-pager suitable for a
CIO/CDO review.

Reply **`next`** to generate the capstone.
