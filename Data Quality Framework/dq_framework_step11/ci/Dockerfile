# =====================================================================
# Multi-stage Dockerfile for the DQ pipeline runner.
# Image is consumed by Airflow KubernetesPodOperator / Prefect / ad-hoc.
# Final image: python:3.11-slim + psql client + pipeline code, ~120 MB.
# =====================================================================

# ---- Stage 1: build wheels ----
FROM python:3.11-slim AS builder
WORKDIR /build
COPY requirements.txt .
RUN pip wheel --wheel-dir /wheels -r requirements.txt

# ---- Stage 2: runtime ----
FROM python:3.11-slim AS runtime

ARG GIT_SHA=dev
LABEL org.opencontainers.image.title="dq-runner" \
      org.opencontainers.image.source="https://github.com/acme/dq-framework" \
      org.opencontainers.image.revision="${GIT_SHA}"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    OTEL_SERVICE_NAME=dq-runner \
    OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf

# Postgres client + tini for proper PID-1 signal handling
RUN apt-get update && apt-get install -y --no-install-recommends \
        postgresql-client tini ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

# Non-root user (least privilege)
RUN useradd --create-home --uid 10001 dq
USER dq
WORKDIR /home/dq/app

COPY --from=builder /wheels /wheels
RUN pip install --user --no-index --find-links=/wheels /wheels/*.whl

# Application code (copy last for best layer cache)
COPY --chown=dq:dq engine/      ./engine/
COPY --chown=dq:dq exporters/   ./exporters/
COPY --chown=dq:dq alerting/    ./alerting/
COPY --chown=dq:dq sql/         ./sql/
COPY --chown=dq:dq scripts/     ./scripts/

# Health probe used by KubernetesPodOperator
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python -c "import engine; print('ok')" || exit 1

ENTRYPOINT ["/usr/bin/tini","--"]
CMD ["python","-m","engine.pipeline","--help"]
