"""
Scorecard exporter — generates CSV + Excel + HTML artifacts from reporting views.

Usage:
    python scorecard_exporter.py --execution-id 42 --out ./exports
    python scorecard_exporter.py --since 2026-06-01 --out ./exports
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
import psycopg2
from dotenv import load_dotenv

load_dotenv()


def _conn():
    return psycopg2.connect(
        host=os.environ["DQ_PG_HOST"],
        port=os.environ.get("DQ_PG_PORT", "5432"),
        dbname=os.environ["DQ_PG_DB"],
        user=os.environ["DQ_PG_USER"],
        password=os.environ["DQ_PG_PASSWORD"],
    )


VIEWS = {
    "executive_scorecard":  "SELECT * FROM reporting.v_executive_scorecard {where} ORDER BY started_at DESC",
    "rule_results_detail":  "SELECT * FROM reporting.v_rule_results_detail {where} ORDER BY executed_at DESC",
    "dimension_trend":      "SELECT * FROM reporting.v_dimension_trend {where_date} ORDER BY run_date DESC, dimension",
    "table_health":         "SELECT * FROM reporting.v_table_health ORDER BY health_score_pct ASC",
    "quarantine_backlog":   "SELECT * FROM reporting.v_quarantine_backlog ORDER BY open_rows DESC",
    "active_alerts":        "SELECT * FROM reporting.v_active_alerts ORDER BY triggered_at DESC",
}


def _build_where(execution_id: int | None, since: str | None) -> tuple[str, str]:
    clauses = []
    if execution_id is not None:
        clauses.append(f"execution_id = {execution_id}")
    if since:
        clauses.append(f"started_at >= '{since}'")
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    where_date = f"WHERE run_date >= '{since}'" if since else ""
    return where, where_date


def export(execution_id: int | None, since: str | None, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    where, where_date = _build_where(execution_id, since)

    frames: dict[str, pd.DataFrame] = {}
    with _conn() as cx:
        for name, sql in VIEWS.items():
            q = sql.format(where=where, where_date=where_date)
            frames[name] = pd.read_sql(q, cx)

    # --- CSVs (one per view) ----------------------------------------
    for name, df in frames.items():
        df.to_csv(out_dir / f"{name}_{ts}.csv", index=False)

    # --- Single Excel workbook with one tab per view ----------------
    xlsx_path = out_dir / f"dq_scorecard_{ts}.xlsx"
    with pd.ExcelWriter(xlsx_path, engine="openpyxl") as xl:
        for name, df in frames.items():
            df.to_excel(xl, sheet_name=name[:31], index=False)

    # --- HTML executive summary -------------------------------------
    html_path = out_dir / f"dq_scorecard_{ts}.html"
    _render_html(frames, html_path)

    print(f"[exporter] wrote {len(frames)} CSVs, {xlsx_path.name}, {html_path.name}")
    return xlsx_path


def _render_html(frames: dict[str, pd.DataFrame], path: Path) -> None:
    css = """
    <style>
      body { font-family: -apple-system, Segoe UI, sans-serif; max-width: 1200px; margin: 2em auto; color:#1a1a1a; }
      h1 { border-bottom: 3px solid #0b5394; padding-bottom: 6px; }
      h2 { color: #0b5394; margin-top: 2em; }
      table { border-collapse: collapse; width: 100%; font-size: 13px; }
      th { background: #0b5394; color: #fff; padding: 6px; text-align: left; }
      td { padding: 5px 6px; border-bottom: 1px solid #eee; }
      tr:nth-child(even) td { background: #f7f9fc; }
      .pill { padding: 2px 8px; border-radius: 10px; font-size: 11px; font-weight: 600; }
      .PASS { background:#d4edda; color:#155724; }
      .WARN { background:#fff3cd; color:#856404; }
      .FAIL,.ERROR { background:#f8d7da; color:#721c24; }
    </style>
    """
    parts = [css, f"<h1>Data Quality Scorecard</h1><p>Generated {datetime.utcnow().isoformat()}Z</p>"]
    for name, df in frames.items():
        parts.append(f"<h2>{name.replace('_',' ').title()}</h2>")
        parts.append(df.head(200).to_html(index=False, escape=False) if not df.empty else "<p><em>No rows.</em></p>")
    path.write_text("".join(parts), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--execution-id", type=int)
    ap.add_argument("--since")
    ap.add_argument("--out", default="./exports")
    args = ap.parse_args()
    export(args.execution_id, args.since, Path(args.out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
