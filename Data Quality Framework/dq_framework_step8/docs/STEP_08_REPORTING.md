# Step 8 — Reporting Layer, Scorecards & Alerting

## Goal
Turn the operational tables built in Steps 1–7 into **consumable insight**:
executive scorecards, BI-ready views for Power BI / Tableau / Looker, exportable
artifacts (CSV / Excel / HTML), and multi-channel alerting.

## Components

| File | Purpose |
|------|---------|
| `sql/11_reporting_views.sql`               | 6 BI views in dedicated `reporting` schema |
| `python/reporting/scorecard_exporter.py`   | CSV + Excel + HTML artifact generator     |
| `python/reporting/alerting.py`             | Slack / Teams / Email / PagerDuty dispatch |
| `python/reporting/requirements.txt`        | Python deps                                |
| `python/reporting/.env.example`            | Channel + DB config template               |

## Reporting Views

| View | Use case | Refresh grain |
|------|----------|---------------|
| `v_executive_scorecard`   | KPI tiles — pass %, fail counts, duration | per execution |
| `v_rule_results_detail`   | Drill-down rule table                     | per execution |
| `v_dimension_trend`       | DAMA-DMBOK 6-dimension line chart         | daily         |
| `v_table_health`          | Heat-map of table health (last 30d)       | rolling 30d   |
| `v_quarantine_backlog`    | Open quarantine rows by age bucket        | live          |
| `v_active_alerts`         | Unified alert feed (rules + ETL + SLA)    | live          |

All views live in the `reporting` schema. Grant `SELECT` to a dedicated
`bi_reader` role; BI tools connect with that role only (least privilege).

## Connecting BI tools

### Power BI
1. Get Data → PostgreSQL → host/db
2. Navigator → check the `reporting` schema views
3. Set scheduled refresh to align with pipeline cadence

### Tableau
1. New Data Source → PostgreSQL
2. Drag any `reporting.v_*` view onto canvas — no custom SQL needed
3. Publish data source so analysts inherit governance

### Looker / LookML
Map each view to an `explore`; `v_executive_scorecard` is the primary,
others join on `execution_id` / `target_table`.

## Exporter

```bash
cd python/reporting
pip install -r requirements.txt
cp .env.example .env   # fill DB creds
python scorecard_exporter.py --since 2026-06-01 --out ./exports
```

Produces (per run):
* `{view}_{ts}.csv` — one CSV per view (machine-friendly)
* `dq_scorecard_{ts}.xlsx` — multi-tab workbook (steward-friendly)
* `dq_scorecard_{ts}.html` — self-contained HTML email-ready summary

## Alerting

```bash
python alerting.py
```

Channel selection is **config-driven**: any channel with empty env vars is
skipped silently. PagerDuty only fires for `CRITICAL` severity, matching
the on-call escalation policy of most Fortune-500 SRE teams.

### Severity routing matrix

| Severity | Slack | Teams | Email | PagerDuty |
|----------|:-----:|:-----:|:-----:|:---------:|
| LOW      |   ✓   |   ✓   |       |           |
| MEDIUM   |   ✓   |   ✓   |   ✓   |           |
| HIGH     |   ✓   |   ✓   |   ✓   |           |
| CRITICAL |   ✓   |   ✓   |   ✓   |     ✓     |

(All non-PD channels currently send every alert returned by
`v_active_alerts`; filter inside each adapter if you need tighter routing.)

## Fortune-500 alignment

* **Separation of duties** — `reporting` schema is read-only for BI accounts.
* **Auditability** — every exported artifact is timestamped (UTC) and
  reproducible from `execution_id`.
* **Deduplication** — PagerDuty `dedup_key` prevents alert storms during
  systemic outages.
* **Channel resilience** — failure of one channel does not block others
  (each adapter is wrapped in its own `try/except`).
* **Self-serve analytics** — business-friendly column aliases and pre-joined
  views remove the need for analysts to know the operational schema.

## Verification

```sql
-- Quick smoke after a pipeline run
SELECT * FROM reporting.v_executive_scorecard ORDER BY started_at DESC LIMIT 5;
SELECT * FROM reporting.v_active_alerts;
```

## Next (Step 9 preview)
End-to-end demo dataset + a single `make demo` command that spins up the
full framework against a synthetic Northwind-style schema so reviewers can
see every step working without bringing their own data.
