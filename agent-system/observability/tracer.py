"""
ARIA Agent System — OpenTelemetry Tracing.
Crea spans para cada paso de agente, herramienta y petición API.
Correlaciona todo via trace_id + correlation_id.
"""
from __future__ import annotations

import logging
import time
import uuid
from contextlib import contextmanager, asynccontextmanager
from typing import Any, Generator

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.trace.sampling import ParentBasedTraceIdRatio
from opentelemetry.trace import Span, Status, StatusCode, SpanKind

from observability.config import obs_settings

logger = logging.getLogger("aria.observability.tracer")

# ── Globals ──
_tracer: trace.Tracer | None = None
_tracer_provider: TracerProvider | None = None


def setup_tracer() -> trace.Tracer:
    """
    Inicializa el tracer de OpenTelemetry con exportador OTLP.
    """
    global _tracer, _tracer_provider

    if _tracer is not None:
        return _tracer

    resource = Resource.create({
        "service.name": obs_settings.SERVICE_NAME,
        "service.version": "0.2.0",
        "deployment.environment": "production",
    })

    _tracer_provider = TracerProvider(
        resource=resource,
        sampler=ParentBasedTraceIdRatio(obs_settings.TRACES_SAMPLER_ARG),
    )

    # Exportador OTLP (Grafana Tempo / Jaeger / SigNoz)
    try:
        otlp_exporter = OTLPSpanExporter(
            endpoint=obs_settings.EXPORTER_OTLP_ENDPOINT,
            headers=obs_settings.EXPORTER_OTLP_HEADERS,
            insecure=True,
        )
        _tracer_provider.add_span_processor(
            BatchSpanProcessor(otlp_exporter, max_export_batch_size=100)
        )
        logger.info("OTLP exporter configurado: %s", obs_settings.EXPORTER_OTLP_ENDPOINT)
    except Exception as e:
        logger.warning("OTLP exporter no disponible: %s", e)

    # También consola para debug
    from opentelemetry.sdk.trace.export import ConsoleSpanExporter
    _tracer_provider.add_span_processor(
        BatchSpanProcessor(ConsoleSpanExporter(), max_export_batch_size=10)
    )

    trace.set_tracer_provider(_tracer_provider)
    _tracer = trace.get_tracer(__name__)

    logger.info("OpenTelemetry tracer inicializado: %s", obs_settings.SERVICE_NAME)
    return _tracer


def get_tracer() -> trace.Tracer:
    """Retorna el tracer global."""
    global _tracer
    if _tracer is None:
        return setup_tracer()
    return _tracer


def shutdown_tracer() -> None:
    """Cierra el tracer y exporta spans pendientes."""
    global _tracer_provider
    if _tracer_provider:
        _tracer_provider.shutdown()
        _tracer_provider = None
    logger.info("OpenTelemetry tracer detenido")


# ── Context Managers para Spans ─────────────────────────

@asynccontextmanager
async def trace_agent_step(
    agent_type: str,
    task_id: str,
    step: int,
    action: str,
    correlation_id: str | None = None,
):
    """
    Crea un span para un paso de agente.
    Uso: async with trace_agent_step("planner", task_id, 1, "generate_plan"): ...

    Esto genera una traza como:
    task_id → planner.generate_plan → execution.execute_step → verification.validate
    """
    tracer = get_tracer()
    span_name = f"{agent_type}.{action}"
    correlation_id = correlation_id or uuid.uuid4().hex

    with tracer.start_as_current_span(
        span_name,
        kind=SpanKind.INTERNAL,
        attributes={
            "task.id": task_id,
            "agent.type": agent_type,
            "agent.step": step,
            "agent.action": action,
            "correlation.id": correlation_id,
        },
    ) as span:
        start = time.time()
        try:
            yield span
            span.set_status(Status(StatusCode.OK))
        except Exception as e:
            span.set_status(Status(StatusCode.ERROR, str(e)[:500]))
            span.record_exception(e)
            raise
        finally:
            duration_ms = int((time.time() - start) * 1000)
            span.set_attribute("duration_ms", duration_ms)


@asynccontextmanager
async def trace_tool_execution(
    tool_name: str,
    task_id: str,
    params: dict[str, Any] | None = None,
    correlation_id: str | None = None,
):
    """
    Crea un span para la ejecución de una herramienta.
    Uso: async with trace_tool_execution("terminal_run", task_id, {"command": "ls"}): ...
    """
    tracer = get_tracer()
    span_name = f"tool.{tool_name}"

    with tracer.start_as_current_span(
        span_name,
        kind=SpanKind.CLIENT,
        attributes={
            "tool.name": tool_name,
            "task.id": task_id,
            "correlation.id": correlation_id or "",
            "params": str(params)[:500] if params else "",
        },
    ) as span:
        start = time.time()
        try:
            yield span
            span.set_status(Status(StatusCode.OK))
        except Exception as e:
            span.set_status(Status(StatusCode.ERROR, str(e)[:500]))
            span.record_exception(e)
            raise
        finally:
            duration_ms = int((time.time() - start) * 1000)
            span.set_attribute("duration_ms", duration_ms)


@asynccontextmanager
async def trace_api_request(
    endpoint: str,
    method: str,
    user_id: str | None = None,
):
    """
    Crea un span para una petición API.
    Uso: async with trace_api_request("/api/v1/tasks", "POST"): ...
    """
    tracer = get_tracer()
    span_name = f"api.{method}.{endpoint.replace('/', '_')}"

    with tracer.start_as_current_span(
        span_name,
        kind=SpanKind.SERVER,
        attributes={
            "http.method": method,
            "http.route": endpoint,
            "user.id": user_id or "anonymous",
        },
    ) as span:
        start = time.time()
        try:
            yield span
            span.set_status(Status(StatusCode.OK))
        except Exception as e:
            span.set_status(Status(StatusCode.ERROR, str(e)[:500]))
            span.record_exception(e)
            raise
        finally:
            duration_ms = int((time.time() - start) * 1000)
            span.set_attribute("duration_ms", duration_ms)
            span.set_attribute("http.response_time_ms", duration_ms)


# ── Función helper para correlation_id ──────────────────

def generate_correlation_id() -> str:
    """Genera un correlation_id único para seguimiento de flujo completo."""
    return f"corr-{uuid.uuid4().hex[:24]}"