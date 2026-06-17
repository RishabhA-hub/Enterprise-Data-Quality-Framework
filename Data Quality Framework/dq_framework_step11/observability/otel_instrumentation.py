"""
otel_instrumentation.py
======================================================================
OpenTelemetry bootstrap for the DQ pipeline runner.

Exports:
  * Traces  -> OTLP/HTTP (Tempo / Datadog / Honeycomb / Jaeger)
  * Metrics -> OTLP/HTTP (Prometheus via collector, or Datadog)
  * Logs    -> stdlib logging bridge (structured JSON)

Auto-instruments:
  * psycopg / psycopg2          (DB calls + bind parameters redacted)
  * requests / urllib3          (alerting webhooks)
  * logging                     (trace_id/span_id correlation)

Usage (call ONCE at process start):
    from observability.otel_instrumentation import init_observability
    init_observability(service="dq-rule-engine", env="prd")
"""

from __future__ import annotations
import logging
import os
from typing import Optional

from opentelemetry import metrics, trace
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.logging import LoggingInstrumentor
from opentelemetry.instrumentation.psycopg2 import Psycopg2Instrumentor
from opentelemetry.instrumentation.requests import RequestsInstrumentor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

_log = logging.getLogger(__name__)
_INITIALISED = False


# --------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------- #
def init_observability(
    service: str,
    env: str,
    version: Optional[str] = None,
    otlp_endpoint: Optional[str] = None,
) -> None:
    """Idempotent OTEL bootstrap. Safe to call multiple times."""
    global _INITIALISED
    if _INITIALISED:
        return

    endpoint = otlp_endpoint or os.getenv(
        "OTEL_EXPORTER_OTLP_ENDPOINT", "http://otel-collector:4318"
    )

    resource = Resource.create({
        "service.name":      service,
        "service.version":   version or os.getenv("GIT_SHA", "dev"),
        "deployment.environment": env,
        "host.name":         os.uname().nodename,
    })

    # ---- Tracing --------------------------------------------------- #
    tp = TracerProvider(resource=resource)
    tp.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter(endpoint=f"{endpoint}/v1/traces"))
    )
    trace.set_tracer_provider(tp)

    # ---- Metrics --------------------------------------------------- #
    reader = PeriodicExportingMetricReader(
        OTLPMetricExporter(endpoint=f"{endpoint}/v1/metrics"),
        export_interval_millis=15_000,
    )
    metrics.set_meter_provider(MeterProvider(resource=resource, metric_readers=[reader]))

    # ---- Auto-instrumentation ------------------------------------- #
    Psycopg2Instrumentor().instrument(enable_commenter=True, commenter_options={
        "db_driver": True, "opentelemetry_values": True,
    })
    RequestsInstrumentor().instrument()
    LoggingInstrumentor().instrument(set_logging_format=True)

    _INITIALISED = True
    _log.info("OpenTelemetry initialised", extra={
        "service": service, "env": env, "endpoint": endpoint,
    })


# --------------------------------------------------------------------- #
# Standard custom metrics shared across pipeline stages
# --------------------------------------------------------------------- #
_meter = metrics.get_meter("dq.pipeline")

RULES_EXECUTED = _meter.create_counter(
    "dq.rules.executed",
    unit="1",
    description="Number of DQ rules executed",
)

RULE_DURATION = _meter.create_histogram(
    "dq.rule.duration_ms",
    unit="ms",
    description="Per-rule execution duration in milliseconds",
)

RULE_PASS_RATE = _meter.create_observable_gauge(
    "dq.rule.pass_rate",
    unit="1",
    description="Rolling pass rate (0..1) per data domain",
    callbacks=[],          # populated at runtime by the scorecard exporter
)

RECON_GAP_ROWS = _meter.create_counter(
    "dq.recon.gap_rows",
    unit="rows",
    description="Total reconciliation gap rows detected",
)

SLA_BREACHES = _meter.create_counter(
    "dq.sla.breaches",
    unit="1",
    description="SLA breach events emitted by the alerting module",
)
