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
from apps.core.observability.tracing import get_tracer, get_trace_id, setup_tracing
from apps.core.observability.metrics import get_meter, AriaMetrics
from apps.core.observability.logging import get_logger

__all__ = [
    "get_tracer",
    "get_trace_id",
    "setup_tracing",
    "get_meter",
    "AriaMetrics",
    "get_logger",
]
