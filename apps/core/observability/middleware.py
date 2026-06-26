"""
FastAPI middleware for automatic request tracing, metrics, and structured logging.

Every incoming HTTP request gets:
  - An OTel span with route, method, status code attributes
  - Request ID injected into headers + log context
  - Prometheus metric increments
  - Structured log line on response (method, path, status, latency_ms)

Install in main.py:
    from apps.core.observability.middleware import AriaObservabilityMiddleware
    app.add_middleware(AriaObservabilityMiddleware)
"""

from __future__ import annotations

import time
import uuid
from typing import TYPE_CHECKING

from starlette.middleware.base import BaseHTTPMiddleware

from apps.core.observability.logging import get_logger
from apps.core.observability.metrics import get_metrics
from apps.core.observability.tracing import get_tracer

if TYPE_CHECKING:
    from collections.abc import Callable

    from starlette.requests import Request
    from starlette.responses import Response
    from starlette.types import ASGIApp

logger = get_logger("aria.middleware")
_tracer = get_tracer("aria.http")


class AriaObservabilityMiddleware(BaseHTTPMiddleware):
    """
    Production-grade ASGI middleware that instruments every HTTP request.

    Responsibilities:
    - Starts an OTel span per request with standard HTTP attributes
    - Injects X-Request-ID header (generates if not present)
    - Records request/error counts in AriaMetrics
    - Emits a structured log line after each response

    Skips observability overhead for non-essential paths:
    - /health (load-balancer heartbeats)
    - /metrics (scrape endpoint itself)
    - /static/* (no static files, but future-proof)
    """

    _SKIP_PATHS = frozenset({"/health", "/metrics"})

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)
        self._metrics = get_metrics()

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if request.url.path in self._SKIP_PATHS:
            return await call_next(request)

        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        start_ns = time.perf_counter_ns()

        span_name = f"{request.method} {request.url.path}"

        with _tracer.start_as_current_span(span_name) as span:
            span.set_attribute("http.method", request.method)
            span.set_attribute("http.url", str(request.url))
            span.set_attribute("http.route", request.url.path)
            span.set_attribute("aria.request_id", request_id)

            response: Response | None = None

            try:
                response = await call_next(request)
                span.set_attribute("http.status_code", response.status_code)
                response.headers["X-Request-ID"] = request_id

                is_error = response.status_code >= 500
                self._metrics.record_request(error=is_error)

                if is_error:
                    try:
                        from opentelemetry.trace import StatusCode

                        span.set_status(StatusCode.ERROR, f"HTTP {response.status_code}")
                    except ImportError:
                        pass

                return response

            except Exception as exc:
                self._metrics.record_request(error=True)

                try:
                    span.record_exception(exc, escaped=True)
                    from opentelemetry.trace import StatusCode

                    span.set_status(StatusCode.ERROR, str(exc))
                except ImportError:
                    pass

                raise

            finally:
                latency_ms = (time.perf_counter_ns() - start_ns) // 1_000_000
                status_code = response.status_code if response is not None else 500

                logger.info(
                    "%s %s %d %dms",
                    request.method,
                    request.url.path,
                    status_code,
                    latency_ms,
                    extra={
                        "request_id": request_id,
                        "method": request.method,
                        "path": request.url.path,
                        "status_code": status_code,
                        "latency_ms": latency_ms,
                        "client": request.client.host if request.client else "unknown",
                    },
                )
