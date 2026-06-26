"""
ARIA Observability — Production-grade telemetry, tracing, and metrics.

Stack:
  - OpenTelemetry SDK for distributed tracing (OTLP export)
  - Structured JSON logging with trace correlation
  - Prometheus-compatible metrics
  - Sentry for error aggregation
  - Custom ARIA business metrics

Usage:
    from apps.core.observability import get_tracer, get_meter, logger

    tracer = get_tracer(__name__)
    with tracer.start_as_current_span("my_operation") as span:
        span.set_attribute("aria.component", "income_loop")
        ...
"""

from apps.core.observability.logging import get_logger
from apps.core.observability.metrics import AriaMetrics, get_meter
from apps.core.observability.tracing import get_trace_id, get_tracer, setup_tracing

__all__ = [
    "get_tracer",
    "get_trace_id",
    "setup_tracing",
    "get_meter",
    "AriaMetrics",
    "get_logger",
]
