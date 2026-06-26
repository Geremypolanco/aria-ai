"""
otel_engine.py — Observabilidad Completa para ARIA AI.

Integra OpenTelemetry, Prometheus y Grafana para:
  - Rastreo distribuido de todas las operaciones (OpenTelemetry)
  - Métricas de negocio y sistema en tiempo real (Prometheus)
  - Visualización de dashboards ejecutivos (Grafana)

Extiende el trace_engine.py existente con observabilidad de nivel producción.

Arquitectura:
    ARIA Agents → OpenTelemetry SDK → OTLP Exporter → Prometheus → Grafana

Referencia:
  - OpenTelemetry: https://opentelemetry.io/docs/instrumentation/python/
  - Prometheus: https://github.com/prometheus/client_python
  - Grafana: https://grafana.com/docs/
"""
from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager, contextmanager
from typing import Any, AsyncGenerator, Generator, Optional

logger = logging.getLogger("aria.otel_engine")

# ── OpenTelemetry Import con fallback ────────────────────────────────────────
try:
    from opentelemetry import trace, metrics
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    from opentelemetry.sdk.metrics import MeterProvider
    from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
    from opentelemetry.sdk.resources import Resource, SERVICE_NAME
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
    from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
    OTEL_AVAILABLE = True
    logger.info("[OpenTelemetry] SDK cargado correctamente.")
except ImportError:
    OTEL_AVAILABLE = False
    logger.warning(
        "[OpenTelemetry] SDK no instalado. "
        "Usando tracing nativo. "
        "Instala con: pip install opentelemetry-sdk opentelemetry-exporter-otlp"
    )
    trace = None  # type: ignore[assignment]
    metrics = None  # type: ignore[assignment]

# ── Prometheus Import con fallback ───────────────────────────────────────────
try:
    from prometheus_client import (
        Counter, Gauge, Histogram, Summary,
        CollectorRegistry, generate_latest, CONTENT_TYPE_LATEST,
        start_http_server,
    )
    PROMETHEUS_AVAILABLE = True
    logger.info("[Prometheus] Client cargado correctamente.")
except ImportError:
    PROMETHEUS_AVAILABLE = False
    logger.warning(
        "[Prometheus] prometheus-client no instalado. "
        "Instala con: pip install prometheus-client"
    )
    Counter = None  # type: ignore[assignment,misc]
    Gauge = None  # type: ignore[assignment,misc]
    Histogram = None  # type: ignore[assignment,misc]


# ── FastAPI Instrumentation ──────────────────────────────────────────────────
try:
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    FASTAPI_INSTRUMENTATION_AVAILABLE = True
except ImportError:
    FASTAPI_INSTRUMENTATION_AVAILABLE = False
    FastAPIInstrumentor = None  # type: ignore[assignment,misc]


# ── Métricas de Prometheus para ARIA ────────────────────────────────────────

class AriaPrometheusMetrics:
    """
    Métricas de Prometheus para ARIA AI.

    Expone métricas de negocio y sistema en /metrics para Prometheus.
    Grafana visualiza estas métricas en dashboards ejecutivos.
    """

    def __init__(self) -> None:
        self._initialized = False
        self._registry: Any = None
        self._metrics: dict[str, Any] = {}

        if PROMETHEUS_AVAILABLE:
            self._setup_metrics()

    def _setup_metrics(self) -> None:
        """Configura todas las métricas de Prometheus para ARIA."""
        try:
            # ── Métricas de Negocio ────────────────────────────────────────
            self._metrics["revenue_total"] = Counter(
                "aria_revenue_total_usd",
                "Ingresos totales generados por ARIA en USD",
                ["channel", "product", "agent"],
            )

            self._metrics["sales_total"] = Counter(
                "aria_sales_total",
                "Número total de ventas completadas",
                ["product", "channel"],
            )

            self._metrics["leads_generated"] = Counter(
                "aria_leads_generated_total",
                "Número total de leads generados",
                ["source", "niche"],
            )

            self._metrics["campaigns_active"] = Gauge(
                "aria_campaigns_active",
                "Número de campañas activas en este momento",
                ["channel"],
            )

            # ── Métricas de Agentes ────────────────────────────────────────
            self._metrics["agent_executions"] = Counter(
                "aria_agent_executions_total",
                "Total de ejecuciones por agente",
                ["agent_name", "success"],
            )

            self._metrics["agent_duration"] = Histogram(
                "aria_agent_duration_seconds",
                "Duración de ejecución de agentes en segundos",
                ["agent_name"],
                buckets=[0.1, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0],
            )

            self._metrics["agent_roi"] = Gauge(
                "aria_agent_roi_usd",
                "ROI actual por agente en USD",
                ["agent_name"],
            )

            # ── Métricas de Sistema ────────────────────────────────────────
            self._metrics["llm_calls"] = Counter(
                "aria_llm_calls_total",
                "Total de llamadas al LLM",
                ["model", "agent"],
            )

            self._metrics["llm_tokens"] = Counter(
                "aria_llm_tokens_total",
                "Total de tokens consumidos",
                ["model", "type"],  # type: input/output
            )

            self._metrics["memory_operations"] = Counter(
                "aria_memory_operations_total",
                "Operaciones de memoria (Supabase, Redis, Graphiti, Zep)",
                ["backend", "operation"],
            )

            self._metrics["crawl_requests"] = Counter(
                "aria_crawl_requests_total",
                "Requests de crawling (Crawl4AI, Firecrawl)",
                ["source", "success"],
            )

            self._metrics["experiments_active"] = Gauge(
                "aria_experiments_active",
                "Experimentos A/B activos (GrowthBook)",
            )

            self._metrics["autonomous_cycles"] = Counter(
                "aria_autonomous_cycles_total",
                "Ciclos autónomos completados",
                ["status"],
            )

            self._initialized = True
            logger.info("[Prometheus] %d métricas configuradas", len(self._metrics))

        except Exception as exc:
            logger.error("[Prometheus] Error configurando métricas: %s", exc)

    def record_revenue(
        self,
        amount_usd: float,
        channel: str = "unknown",
        product: str = "unknown",
        agent: str = "unknown",
    ) -> None:
        """Registra ingresos generados."""
        if not self._initialized:
            return
        try:
            self._metrics["revenue_total"].labels(
                channel=channel, product=product, agent=agent
            ).inc(amount_usd)
            self._metrics["sales_total"].labels(
                product=product, channel=channel
            ).inc()
        except Exception as exc:
            logger.debug("[Prometheus] Error registrando revenue: %s", exc)

    def record_agent_execution(
        self,
        agent_name: str,
        success: bool,
        duration_seconds: float,
        roi: float = 0.0,
    ) -> None:
        """Registra la ejecución de un agente."""
        if not self._initialized:
            return
        try:
            self._metrics["agent_executions"].labels(
                agent_name=agent_name,
                success=str(success).lower(),
            ).inc()
            self._metrics["agent_duration"].labels(
                agent_name=agent_name
            ).observe(duration_seconds)
            if roi != 0:
                self._metrics["agent_roi"].labels(agent_name=agent_name).set(roi)
        except Exception as exc:
            logger.debug("[Prometheus] Error registrando agente: %s", exc)

    def record_llm_call(
        self,
        model: str,
        agent: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
    ) -> None:
        """Registra una llamada al LLM."""
        if not self._initialized:
            return
        try:
            self._metrics["llm_calls"].labels(model=model, agent=agent).inc()
            if input_tokens:
                self._metrics["llm_tokens"].labels(model=model, type="input").inc(input_tokens)
            if output_tokens:
                self._metrics["llm_tokens"].labels(model=model, type="output").inc(output_tokens)
        except Exception as exc:
            logger.debug("[Prometheus] Error registrando LLM call: %s", exc)

    def record_crawl(self, source: str, success: bool) -> None:
        """Registra un request de crawling."""
        if not self._initialized:
            return
        try:
            self._metrics["crawl_requests"].labels(
                source=source, success=str(success).lower()
            ).inc()
        except Exception as exc:
            logger.debug("[Prometheus] Error registrando crawl: %s", exc)

    def record_autonomous_cycle(self, status: str = "completed") -> None:
        """Registra un ciclo autónomo."""
        if not self._initialized:
            return
        try:
            self._metrics["autonomous_cycles"].labels(status=status).inc()
        except Exception as exc:
            logger.debug("[Prometheus] Error registrando ciclo: %s", exc)

    def get_metrics_text(self) -> str:
        """Genera el texto de métricas en formato Prometheus."""
        if not PROMETHEUS_AVAILABLE:
            return "# Prometheus no disponible\n"
        try:
            from prometheus_client import generate_latest, REGISTRY
            return generate_latest(REGISTRY).decode("utf-8")
        except Exception as exc:
            return f"# Error generando métricas: {exc}\n"

    def start_metrics_server(self, port: int = 9090) -> None:
        """Inicia el servidor HTTP de métricas de Prometheus."""
        if not PROMETHEUS_AVAILABLE:
            logger.warning("[Prometheus] No disponible, no se puede iniciar servidor")
            return
        try:
            start_http_server(port)
            logger.info("[Prometheus] Servidor de métricas iniciado en puerto %d", port)
        except Exception as exc:
            logger.error("[Prometheus] Error iniciando servidor: %s", exc)


# ── OpenTelemetry Tracer ─────────────────────────────────────────────────────

class AriaOtelTracer:
    """
    Tracer de OpenTelemetry para ARIA AI.

    Rastrea todas las operaciones de agentes con spans distribuidos,
    permitiendo análisis de latencia, errores y dependencias.
    """

    def __init__(
        self,
        service_name: str = "aria-ai",
        otlp_endpoint: str = "http://localhost:4317",
    ) -> None:
        self._service_name = service_name
        self._otlp_endpoint = otlp_endpoint
        self._tracer: Any = None
        self._initialized = False

    def initialize(self) -> bool:
        """Inicializa el TracerProvider de OpenTelemetry."""
        if not OTEL_AVAILABLE:
            logger.warning("[OpenTelemetry] SDK no disponible")
            return False

        try:
            resource = Resource.create({SERVICE_NAME: self._service_name})

            # Configurar exporter OTLP (para Jaeger, Tempo, etc.)
            otlp_exporter = OTLPSpanExporter(endpoint=self._otlp_endpoint)

            provider = TracerProvider(resource=resource)
            provider.add_span_processor(BatchSpanProcessor(otlp_exporter))
            trace.set_tracer_provider(provider)

            self._tracer = trace.get_tracer(self._service_name)
            self._initialized = True
            logger.info("[OpenTelemetry] TracerProvider inicializado (endpoint=%s)", self._otlp_endpoint)
            return True

        except Exception as exc:
            logger.warning("[OpenTelemetry] Error inicializando: %s — usando noop tracer", exc)
            if OTEL_AVAILABLE:
                self._tracer = trace.get_tracer(self._service_name)
                self._initialized = True
            return False

    def instrument_fastapi(self, app: Any) -> None:
        """Instrumenta automáticamente la app FastAPI de ARIA."""
        if not FASTAPI_INSTRUMENTATION_AVAILABLE:
            logger.warning("[OpenTelemetry] FastAPI instrumentation no disponible")
            return
        try:
            FastAPIInstrumentor.instrument_app(app)
            logger.info("[OpenTelemetry] FastAPI instrumentado correctamente")
        except Exception as exc:
            logger.warning("[OpenTelemetry] Error instrumentando FastAPI: %s", exc)

    @contextmanager
    def trace_operation(
        self,
        operation_name: str,
        attributes: dict[str, Any] | None = None,
    ) -> Generator:
        """
        Context manager para trazar una operación síncrona.

        Uso:
            with tracer.trace_operation("agent.execute", {"agent": "cfo"}):
                result = agent.execute(task)
        """
        if not self._initialized or not OTEL_AVAILABLE:
            yield None
            return

        with self._tracer.start_as_current_span(operation_name) as span:
            if attributes:
                for key, value in attributes.items():
                    span.set_attribute(key, str(value))
            try:
                yield span
            except Exception as exc:
                span.record_exception(exc)
                span.set_status(trace.StatusCode.ERROR, str(exc))
                raise

    @asynccontextmanager
    async def trace_async_operation(
        self,
        operation_name: str,
        attributes: dict[str, Any] | None = None,
    ) -> AsyncGenerator:
        """
        Context manager para trazar una operación asíncrona.

        Uso:
            async with tracer.trace_async_operation("agent.execute", {"agent": "cfo"}):
                result = await agent.execute(task)
        """
        if not self._initialized or not OTEL_AVAILABLE:
            yield None
            return

        with self._tracer.start_as_current_span(operation_name) as span:
            if attributes:
                for key, value in attributes.items():
                    span.set_attribute(key, str(value))
            try:
                yield span
            except Exception as exc:
                span.record_exception(exc)
                span.set_status(trace.StatusCode.ERROR, str(exc))
                raise

    def get_current_trace_id(self) -> str:
        """Retorna el trace ID actual para correlación de logs."""
        if not OTEL_AVAILABLE:
            return ""
        try:
            span = trace.get_current_span()
            ctx = span.get_span_context()
            return format(ctx.trace_id, "032x") if ctx.trace_id else ""
        except Exception:
            return ""


# ── Motor Unificado de Observabilidad ────────────────────────────────────────

class AriaObservabilityEngine:
    """
    Motor unificado de Observabilidad para ARIA AI.

    Combina:
    - OpenTelemetry: rastreo distribuido de operaciones
    - Prometheus: métricas de negocio y sistema
    - Grafana: visualización (vía docker-compose)

    Extiende el trace_engine.py existente con capacidades de producción.

    Integra con:
    - ExecutionPipeline (trazar cada ejecución)
    - BaseAgent (métricas por agente)
    - FastAPI server (instrumentación automática)
    - Todos los agentes especializados
    """

    def __init__(
        self,
        service_name: str = "aria-ai",
        otlp_endpoint: str = "http://localhost:4317",
        prometheus_port: int = 9090,
    ) -> None:
        self.tracer = AriaOtelTracer(
            service_name=service_name,
            otlp_endpoint=otlp_endpoint,
        )
        self.metrics = AriaPrometheusMetrics()
        self._prometheus_port = prometheus_port

    def initialize(self, fastapi_app: Any = None) -> dict[str, bool]:
        """
        Inicializa todos los componentes de observabilidad.

        Args:
            fastapi_app: App FastAPI para instrumentación automática

        Returns:
            Dict con el estado de cada componente
        """
        otel_ok = self.tracer.initialize()

        if fastapi_app:
            self.tracer.instrument_fastapi(fastapi_app)

        return {
            "opentelemetry": otel_ok,
            "prometheus": self.metrics._initialized,
            "fastapi_instrumented": fastapi_app is not None and FASTAPI_INSTRUMENTATION_AVAILABLE,
        }

    def start_metrics_server(self) -> None:
        """Inicia el servidor de métricas de Prometheus."""
        self.metrics.start_metrics_server(self._prometheus_port)

    async def instrument_agent_execution(
        self,
        agent_name: str,
        operation: str,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Instrumenta la ejecución de un agente con tracing y métricas.

        Uso:
            async with engine.instrument_agent_execution("cfo", "generate_revenue"):
                result = await cfo_agent.execute(context)

        Returns:
            Dict con trace_id y metadata de la instrumentación
        """
        start_time = time.monotonic()
        span_name = f"aria.agent.{agent_name}.{operation}"

        trace_id = self.tracer.get_current_trace_id()

        return {
            "trace_id": trace_id,
            "agent": agent_name,
            "operation": operation,
            "start_time": start_time,
            "span_name": span_name,
        }

    def record_execution_complete(
        self,
        instrument_result: dict[str, Any],
        success: bool,
        roi: float = 0.0,
    ) -> None:
        """
        Registra la finalización de una ejecución instrumentada.

        Args:
            instrument_result: Resultado de instrument_agent_execution
            success: Si fue exitosa
            roi: ROI generado
        """
        start_time = instrument_result.get("start_time", time.monotonic())
        duration = time.monotonic() - start_time
        agent_name = instrument_result.get("agent", "unknown")

        self.metrics.record_agent_execution(
            agent_name=agent_name,
            success=success,
            duration_seconds=duration,
            roi=roi,
        )

    def get_health_status(self) -> dict[str, Any]:
        """Estado de salud del sistema de observabilidad."""
        return {
            "opentelemetry": {
                "available": OTEL_AVAILABLE,
                "initialized": self.tracer._initialized,
                "endpoint": self.tracer._otlp_endpoint,
            },
            "prometheus": {
                "available": PROMETHEUS_AVAILABLE,
                "initialized": self.metrics._initialized,
                "metrics_count": len(self.metrics._metrics),
                "port": self._prometheus_port,
            },
            "grafana": {
                "info": "Configurado vía docker-compose.yml",
                "default_port": 3000,
            },
        }


# ── Singleton ────────────────────────────────────────────────────────────────
_observability_instance: AriaObservabilityEngine | None = None


def get_observability_engine() -> AriaObservabilityEngine:
    """Retorna el singleton del motor de Observabilidad de ARIA."""
    global _observability_instance
    if _observability_instance is None:
        import os
        _observability_instance = AriaObservabilityEngine(
            service_name=os.getenv("OTEL_SERVICE_NAME", "aria-ai"),
            otlp_endpoint=os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317"),
            prometheus_port=int(os.getenv("PROMETHEUS_PORT", "9090")),
        )
    return _observability_instance
