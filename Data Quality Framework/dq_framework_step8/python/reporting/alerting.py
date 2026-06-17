"""
Alerting module — polls reporting.v_active_alerts and dispatches to:
  * Slack (incoming webhook)
  * Microsoft Teams (incoming webhook)
  * Email (SMTP)
  * PagerDuty (Events API v2) for CRITICAL only

Channels are pluggable; configure via .env. Missing config = channel skipped.
"""
from __future__ import annotations

import json
import os
import smtplib
import sys
from email.mime.text import MIMEText
from typing import Callable

import psycopg2
import psycopg2.extras
import requests
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


def fetch_alerts() -> list[dict]:
    with _conn() as cx, cx.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT * FROM reporting.v_active_alerts")
        return [dict(r) for r in cur.fetchall()]


# ----------------------------------------------------------------------
# Channel adapters
# ----------------------------------------------------------------------
def send_slack(alerts: list[dict]) -> None:
    url = os.environ.get("SLACK_WEBHOOK_URL")
    if not url or not alerts:
        return
    blocks = [{"type": "header",
               "text": {"type": "plain_text", "text": f"DQ Alerts ({len(alerts)})"}}]
    for a in alerts[:20]:
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn",
                     "text": (f"*{a['alert_type']}* `{a['severity']}`\n"
                              f"• {a['subject']}  →  {a.get('object') or 'n/a'}\n"
                              f"• magnitude: {a['magnitude']}  • at {a['triggered_at']}")}
        })
    requests.post(url, json={"blocks": blocks}, timeout=10).raise_for_status()


def send_teams(alerts: list[dict]) -> None:
    url = os.environ.get("TEAMS_WEBHOOK_URL")
    if not url or not alerts:
        return
    facts = [{"name": a["subject"][:60], "value": f"{a['severity']} — {a['magnitude']}"} for a in alerts[:20]]
    card = {
        "@type": "MessageCard",
        "@context": "https://schema.org/extensions",
        "summary": "DQ Alerts",
        "themeColor": "C00000",
        "title": f"Data Quality Alerts ({len(alerts)})",
        "sections": [{"facts": facts, "markdown": True}],
    }
    requests.post(url, json=card, timeout=10).raise_for_status()


def send_email(alerts: list[dict]) -> None:
    host = os.environ.get("SMTP_HOST")
    if not host or not alerts:
        return
    user = os.environ.get("SMTP_USER", "")
    pw   = os.environ.get("SMTP_PASSWORD", "")
    sender = os.environ.get("ALERT_EMAIL_FROM", "dq-alerts@example.com")
    recipients = os.environ.get("ALERT_EMAIL_TO", "").split(",")
    if not any(recipients):
        return
    body_lines = [f"[{a['severity']}] {a['alert_type']}: {a['subject']} → {a.get('object')} "
                  f"(mag={a['magnitude']}, at {a['triggered_at']})" for a in alerts]
    msg = MIMEText("\n".join(body_lines))
    msg["Subject"] = f"[DQ] {len(alerts)} active alerts"
    msg["From"] = sender
    msg["To"] = ", ".join(recipients)
    with smtplib.SMTP(host, int(os.environ.get("SMTP_PORT", "587"))) as s:
        s.starttls()
        if user:
            s.login(user, pw)
        s.send_message(msg)


def send_pagerduty(alerts: list[dict]) -> None:
    key = os.environ.get("PAGERDUTY_ROUTING_KEY")
    if not key:
        return
    for a in (x for x in alerts if x["severity"] == "CRITICAL"):
        payload = {
            "routing_key": key,
            "event_action": "trigger",
            "dedup_key": f"{a['alert_type']}::{a['subject']}",
            "payload": {
                "summary": f"{a['alert_type']}: {a['subject']}",
                "source": a.get("object") or "dq-framework",
                "severity": "critical",
                "custom_details": a,
            },
        }
        requests.post("https://events.pagerduty.com/v2/enqueue",
                      json=payload, timeout=10).raise_for_status()


CHANNELS: dict[str, Callable[[list[dict]], None]] = {
    "slack": send_slack,
    "teams": send_teams,
    "email": send_email,
    "pagerduty": send_pagerduty,
}


def dispatch() -> int:
    alerts = fetch_alerts()
    # Serialize datetimes for JSON-safe payloads
    for a in alerts:
        for k, v in list(a.items()):
            if hasattr(v, "isoformat"):
                a[k] = v.isoformat()
    if not alerts:
        print("[alerting] no active alerts")
        return 0
    print(f"[alerting] dispatching {len(alerts)} alerts")
    for name, fn in CHANNELS.items():
        try:
            fn(alerts)
            print(f"[alerting] {name}: ok")
        except Exception as exc:  # noqa: BLE001
            print(f"[alerting] {name}: ERROR {exc}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(dispatch())
