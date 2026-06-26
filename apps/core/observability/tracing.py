"""
Distributed tracing via OpenTelemetry.

Supports OTLP export (Grafana Tempo, Jaeger, Honeycomb, Datadog, etc.)
via OTEL_EXPORTER_OTLP_ENDPOINT environment variable.

Falls back gracefully when OTel packages are not installed —
all public APIs return no-op implementations so instrumented code
runs unchanged in all environments.
"""

from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Generator

logger = logging.getLogger("aria.tracing")

_tracer_provider = None
_otel_available = False

try:
    from opentelemetry import trace
    from opentelemetry.sdk.resources import SERVICE_NAME, SERVICE_VERSION, Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
    from opentelemetry.trace.propagation.tracecontext import (
        TraceContextTextMapPropagator,  # noqa: F401
    )

    _otel_available = True
except ImportError:
    pass


def setup_tracing(
    service_name: str = "aria-ai",
    service_version: str = "2.0.0",
    otlp_endpoint: str | None = None,
) -> None:
    """
    Initialize the global TracerProvider.

    Call once at application startup (lifespan).
    Subsequent calls are no-ops.
    """
    global _tracer_provider

    if _tracer_provider is not None:
        return

    if not _otel_available:
        logger.info("[Tracing] OpenTelemetry not installed — running in no-op mode")
        return

    endpoint = otlp_endpoint or os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")

    resource = Resource.create(
        {
            SERVICE_NAME: service_name,
            SERVICE_VERSION: service_version,
            "deployment.environment": os.getenv("ENVIRONMENT", "production"),
            "aria.region": os.getenv("FLY_REGION", "unknown"),
        }
    )

    provider = TracerProvider(resource=resource)

    if endpoint:
        try:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

            otlp_exporter = OTLPSpanExporter(endpoint=endpoint)
            provider.add_span_processor(BatchSpanProcessor(otlp_exporter))
            logger.info("[Tracing] OTLP exporter configured → %s", endpoint)
        except ImportError:
            logger.warning("[Tracing] OTLP HTTP exporter not available, using console")
            provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
    else:
        # Console exporter for local dev only
        if os.getenv("ENVIRONMENT") != "production":
            provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))

    trace.set_tracer_provider(provider)
    _tracer_provider = provider
    logger.info("[Tracing] OpenTelemetry initialized: %s v%s", service_name, service_version)


def get_tracer(name: str) -> Any:
    """
    Return an OpenTelemetry Tracer for the given instrumentation scope.

    Returns a no-op tracer when OTel is not available.
    """
    if not _otel_available:
        return _NoOpTracer()

    from opentelemetry import trace

    return trace.get_tracer(name)


def get_trace_id() -> str:
    """Return the current trace ID as a hex string, or empty string if no active span."""
    if not _otel_available:
        return ""
    try:
        from opentelemetry import trace

        span = trace.get_current_span()
        ctx = span.get_span_context()
        if ctx and ctx.is_valid:
            return format(ctx.trace_id, "032x")
    except Exception:
        pass
    return ""


def get_span_id() -> str:
    """Return the current span ID as a hex string."""
    if not _otel_available:
        return ""
    try:
        from opentelemetry import trace

        span = trace.get_current_span()
        ctx = span.get_span_context()
        if ctx and ctx.is_valid:
            return format(ctx.span_id, "016x")
    except Exception:
        pass
    return ""


# ── No-op implementations ──────────────────────────────────────────────────


class _NoOpSpan:
    def set_attribute(self, key: str, value: Any) -> None: ...
    def set_status(self, *args: Any, **kwargs: Any) -> None: ...
    def record_exception(self, exc: Exception, **kwargs: Any) -> None: ...
    def __enter__(self) -> _NoOpSpan:
        return self

    def __exit__(self, *args: Any) -> None: ...


class _NoOpTracer:
    @contextmanager
    def start_as_current_span(self, name: str, **kwargs: Any) -> Generator[_NoOpSpan, None, None]:
        yield _NoOpSpan()

    def start_span(self, name: str, **kwargs: Any) -> _NoOpSpan:
        return _NoOpSpan()
