"""
ARIA Agent System — Observability Configuration.
Configura OpenTelemetry, logging estructurado y métricas Prometheus.
"""
from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings


class ObservabilitySettings(BaseSettings):
    model_config = {"env_prefix": "OTEL_", "extra": "ignore"}

    # ── OpenTelemetry ──
    SERVICE_NAME: str = "aria-agent-system"
    EXPORTER_OTLP_ENDPOINT: str = "http://otel-collector:4317"
    EXPORTER_OTLP_HEADERS: str = ""
    TRACES_SAMPLER: str = "always_on"
    TRACES_SAMPLER_ARG: float = 1.0

    # ── Prometheus ──
    METRICS_PORT: int = 9090
    METRICS_PATH: str = "/metrics"

    # ── Logging ──
    LOG_FORMAT: str = "json"
    LOG_LEVEL: str = "INFO"
    LOG_FILE: str = ""
    LOG_FILE_MAX_SIZE: int = 100 * 1024 * 1024  # 100MB
    LOG_FILE_BACKUP_COUNT: int = 5

    # ── Grafana Cloud (opcional) ──
    GRAFANA_CLOUD_PROM_URL: str = ""
    GRAFANA_CLOUD_PROM_USER: str = ""
    GRAFANA_CLOUD_PROM_PASSWORD: str = ""
    GRAFANA_CLOUD_LOKI_URL: str = ""
    GRAFANA_CLOUD_LOKI_USER: str = ""
    GRAFANA_CLOUD_LOKI_PASSWORD: str = ""
    GRAFANA_CLOUD_TEMPO_URL: str = ""
    GRAFANA_CLOUD_TEMPO_USER: str = ""
    GRAFANA_CLOUD_TEMPO_PASSWORD: str = ""


obs_settings = ObservabilitySettings()