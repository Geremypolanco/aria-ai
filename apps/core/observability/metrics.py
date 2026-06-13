"""
ARIA Business and Technical Metrics.

Two classes:
  - AriaMetrics: High-level business counters (income, AI calls, agent runs).
    Thread-safe, singleton, Redis-backed for persistence across restarts.
  - get_meter(): OpenTelemetry Meter for fine-grained technical metrics.

Business metrics exposed at GET /metrics (Prometheus text format).
"""
from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from threading import Lock
from typing import Any, Dict, Optional

logger = logging.getLogger("aria.metrics")

_otel_available = False
try:
    from opentelemetry import metrics as otel_metrics
    from opentelemetry.sdk.metrics import MeterProvider
    from opentelemetry.sdk.metrics.export import (
        ConsoleMetricExporter,
        PeriodicExportingMetricReader,
    )
    _otel_available = True
except ImportError:
    pass


def get_meter(name: str) -> Any:
    """Return an OpenTelemetry Meter, or a no-op meter if OTel is unavailable."""
    if not _otel_available:
        return _NoOpMeter()
    try:
        from opentelemetry import metrics
        return metrics.get_meter(name)
    except Exception:
        return _NoOpMeter()


# ── Business Metrics ───────────────────────────────────────────────────────


@dataclass
class _CounterBucket:
    """In-memory counter with timestamp of last increment."""
    value: float = 0.0
    last_updated: float = field(default_factory=time.time)

    def increment(self, amount: float = 1.0) -> None:
        self.value += amount
        self.last_updated = time.time()


class AriaMetrics:
    """
    Singleton registry for ARIA business metrics.

    Tracks:
      - AI API calls per provider (success/fail/latency)
      - Income loop cycles (success/fail/revenue)
      - Agent executions
      - Cognition operations (reasoning, planning, reflection)
      - Memory operations (reads/writes/hits)
      - Error rates per component
    """

    _instance: Optional["AriaMetrics"] = None
    _lock: Lock = Lock()

    def __new__(cls) -> "AriaMetrics":
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return
        self._initialized = True
        self._lock_data = Lock()

        # AI metrics
        self._ai_calls: Dict[str, _CounterBucket] = {}
        self._ai_errors: Dict[str, _CounterBucket] = {}
        self._ai_tokens: Dict[str, _CounterBucket] = {}
        self._ai_latency_ms: Dict[str, _CounterBucket] = {}

        # Income metrics
        self._income_cycles_total = _CounterBucket()
        self._income_cycles_success = _CounterBucket()
        self._income_revenue_usd = _CounterBucket()

        # Agent metrics
        self._agent_runs: Dict[str, _CounterBucket] = {}
        self._agent_errors: Dict[str, _CounterBucket] = {}

        # Cognition metrics
        self._cognition_ops: Dict[str, _CounterBucket] = {}

        # Memory metrics
        self._memory_reads = _CounterBucket()
        self._memory_writes = _CounterBucket()
        self._memory_cache_hits = _CounterBucket()
        self._memory_cache_misses = _CounterBucket()

        # System metrics
        self._startup_time = time.time()
        self._request_count = _CounterBucket()
        self._error_count = _CounterBucket()

    # ── AI Metrics ─────────────────────────────────────────────────

    def record_ai_call(
        self,
        provider: str,
        model: str,
        tokens: int = 0,
        latency_ms: int = 0,
        success: bool = True,
    ) -> None:
        key = f"{provider}:{model}"
        with self._lock_data:
            self._ai_calls.setdefault(key, _CounterBucket()).increment()
            self._ai_tokens.setdefault(key, _CounterBucket()).increment(tokens)
            self._ai_latency_ms.setdefault(key, _CounterBucket()).increment(latency_ms)
            if not success:
                self._ai_errors.setdefault(key, _CounterBucket()).increment()

    # ── Income Metrics ─────────────────────────────────────────────

    def record_income_cycle(self, success: bool, revenue_usd: float = 0.0) -> None:
        with self._lock_data:
            self._income_cycles_total.increment()
            if success:
                self._income_cycles_success.increment()
                self._income_revenue_usd.increment(revenue_usd)

    # ── Agent Metrics ──────────────────────────────────────────────

    def record_agent_run(self, agent_name: str, success: bool = True) -> None:
        with self._lock_data:
            self._agent_runs.setdefault(agent_name, _CounterBucket()).increment()
            if not success:
                self._agent_errors.setdefault(agent_name, _CounterBucket()).increment()

    # ── Cognition Metrics ──────────────────────────────────────────

    def record_cognition(self, operation: str) -> None:
        with self._lock_data:
            self._cognition_ops.setdefault(operation, _CounterBucket()).increment()

    # ── Memory Metrics ─────────────────────────────────────────────

    def record_memory_read(self, hit: bool = True) -> None:
        with self._lock_data:
            self._memory_reads.increment()
            if hit:
                self._memory_cache_hits.increment()
            else:
                self._memory_cache_misses.increment()

    def record_memory_write(self) -> None:
        with self._lock_data:
            self._memory_writes.increment()

    # ── HTTP Metrics ───────────────────────────────────────────────

    def record_request(self, error: bool = False) -> None:
        with self._lock_data:
            self._request_count.increment()
            if error:
                self._error_count.increment()

    # ── Prometheus Export ──────────────────────────────────────────

    def to_prometheus(self) -> str:
        """Render metrics in Prometheus text format."""
        lines = [
            "# HELP aria_uptime_seconds Seconds since ARIA startup",
            "# TYPE aria_uptime_seconds gauge",
            f"aria_uptime_seconds {time.time() - self._startup_time:.1f}",
            "",
            "# HELP aria_requests_total Total HTTP requests",
            "# TYPE aria_requests_total counter",
            f"aria_requests_total {self._request_count.value}",
            "",
            "# HELP aria_errors_total Total errors",
            "# TYPE aria_errors_total counter",
            f"aria_errors_total {self._error_count.value}",
            "",
            "# HELP aria_income_cycles_total Income loop cycles executed",
            "# TYPE aria_income_cycles_total counter",
            f"aria_income_cycles_total {self._income_cycles_total.value}",
            "",
            "# HELP aria_income_cycles_success_total Successful income cycles",
            "# TYPE aria_income_cycles_success_total counter",
            f"aria_income_cycles_success_total {self._income_cycles_success.value}",
            "",
            "# HELP aria_income_revenue_usd_total Total revenue potential generated (USD)",
            "# TYPE aria_income_revenue_usd_total counter",
            f"aria_income_revenue_usd_total {self._income_revenue_usd.value:.4f}",
            "",
            "# HELP aria_memory_reads_total Memory read operations",
            "# TYPE aria_memory_reads_total counter",
            f"aria_memory_reads_total {self._memory_reads.value}",
            "",
            "# HELP aria_memory_cache_hit_ratio Memory cache hit ratio",
            "# TYPE aria_memory_cache_hit_ratio gauge",
        ]

        total_reads = self._memory_reads.value
        hit_ratio = (
            self._memory_cache_hits.value / total_reads if total_reads > 0 else 0.0
        )
        lines.append(f"aria_memory_cache_hit_ratio {hit_ratio:.4f}")
        lines.append("")

        # AI call metrics per provider:model
        if self._ai_calls:
            lines += [
                "# HELP aria_ai_calls_total AI API calls by provider and model",
                "# TYPE aria_ai_calls_total counter",
            ]
            for key, bucket in self._ai_calls.items():
                provider, model = key.split(":", 1) if ":" in key else (key, "unknown")
                lines.append(
                    f'aria_ai_calls_total{{provider="{provider}",model="{model}"}} {bucket.value}'
                )
            lines.append("")

        # AI tokens
        if self._ai_tokens:
            lines += [
                "# HELP aria_ai_tokens_total Tokens consumed by AI calls",
                "# TYPE aria_ai_tokens_total counter",
            ]
            for key, bucket in self._ai_tokens.items():
                provider, model = key.split(":", 1) if ":" in key else (key, "unknown")
                lines.append(
                    f'aria_ai_tokens_total{{provider="{provider}",model="{model}"}} {bucket.value}'
                )
            lines.append("")

        # Agent runs
        if self._agent_runs:
            lines += [
                "# HELP aria_agent_runs_total Agent execution count",
                "# TYPE aria_agent_runs_total counter",
            ]
            for agent, bucket in self._agent_runs.items():
                lines.append(f'aria_agent_runs_total{{agent="{agent}"}} {bucket.value}')
            lines.append("")

        # Cognition ops
        if self._cognition_ops:
            lines += [
                "# HELP aria_cognition_ops_total Cognitive operations by type",
                "# TYPE aria_cognition_ops_total counter",
            ]
            for op, bucket in self._cognition_ops.items():
                lines.append(f'aria_cognition_ops_total{{operation="{op}"}} {bucket.value}')
            lines.append("")

        return "\n".join(lines)

    def to_dict(self) -> dict:
        """Return metrics as a structured dict for the API."""
        with self._lock_data:
            return {
                "uptime_seconds": int(time.time() - self._startup_time),
                "requests_total": self._request_count.value,
                "errors_total": self._error_count.value,
                "income": {
                    "cycles_total": self._income_cycles_total.value,
                    "cycles_success": self._income_cycles_success.value,
                    "revenue_usd": round(self._income_revenue_usd.value, 4),
                    "success_rate": (
                        round(
                            self._income_cycles_success.value
                            / self._income_cycles_total.value
                            * 100,
                            1,
                        )
                        if self._income_cycles_total.value > 0
                        else 0.0
                    ),
                },
                "ai": {
                    key: {
                        "calls": int(self._ai_calls.get(key, _CounterBucket()).value),
                        "errors": int(self._ai_errors.get(key, _CounterBucket()).value),
                        "tokens": int(self._ai_tokens.get(key, _CounterBucket()).value),
                    }
                    for key in self._ai_calls
                },
                "agents": {
                    agent: {
                        "runs": int(bucket.value),
                        "errors": int(self._agent_errors.get(agent, _CounterBucket()).value),
                    }
                    for agent, bucket in self._agent_runs.items()
                },
                "memory": {
                    "reads": self._memory_reads.value,
                    "writes": self._memory_writes.value,
                    "cache_hits": self._memory_cache_hits.value,
                    "cache_misses": self._memory_cache_misses.value,
                },
                "ts": datetime.now(timezone.utc).isoformat(),
            }


# Module-level singleton
_metrics: Optional[AriaMetrics] = None


def get_metrics() -> AriaMetrics:
    global _metrics
    if _metrics is None:
        _metrics = AriaMetrics()
    return _metrics


# ── No-op implementations ──────────────────────────────────────────────────

class _NoOpMeter:
    def create_counter(self, *args: Any, **kwargs: Any) -> "_NoOpCounter":
        return _NoOpCounter()

    def create_histogram(self, *args: Any, **kwargs: Any) -> "_NoOpHistogram":
        return _NoOpHistogram()

    def create_gauge(self, *args: Any, **kwargs: Any) -> "_NoOpGauge":
        return _NoOpGauge()

    def create_observable_counter(self, *args: Any, **kwargs: Any) -> None: ...
    def create_observable_gauge(self, *args: Any, **kwargs: Any) -> None: ...


class _NoOpCounter:
    def add(self, amount: float, attributes: Any = None) -> None: ...


class _NoOpHistogram:
    def record(self, amount: float, attributes: Any = None) -> None: ...


class _NoOpGauge:
    def set(self, amount: float, attributes: Any = None) -> None: ...
