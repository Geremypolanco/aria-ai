"""
Unit tests for the observability layer.

These tests verify:
  - AriaMetrics tracks counters correctly
  - Prometheus export produces valid text format
  - Structured logger produces parseable JSON output
  - Tracing no-ops work without OTel installed
"""
from __future__ import annotations

import json
import logging

import pytest


class TestAriaMetrics:
    def test_income_cycle_tracking(self):
        from apps.core.observability.metrics import AriaMetrics
        m = AriaMetrics()

        m.record_income_cycle(success=True, revenue_usd=42.50)
        m.record_income_cycle(success=True, revenue_usd=10.00)
        m.record_income_cycle(success=False)

        d = m.to_dict()
        assert d["income"]["cycles_total"] == 3
        assert d["income"]["cycles_success"] == 2
        assert abs(d["income"]["revenue_usd"] - 52.50) < 0.01
        assert abs(d["income"]["success_rate"] - 66.7) < 0.1

    def test_ai_call_tracking(self):
        from apps.core.observability.metrics import AriaMetrics
        m = AriaMetrics()

        m.record_ai_call("huggingface", "Qwen/Qwen2.5-72B", tokens=500, latency_ms=1200, success=True)
        m.record_ai_call("groq", "llama-3.3-70b", tokens=200, latency_ms=300, success=True)
        m.record_ai_call("huggingface", "Qwen/Qwen2.5-72B", tokens=100, latency_ms=800, success=False)

        d = m.to_dict()
        hf_key = "huggingface:Qwen/Qwen2.5-72B"
        assert d["ai"][hf_key]["calls"] == 2
        assert d["ai"][hf_key]["errors"] == 1
        assert d["ai"][hf_key]["tokens"] == 600

    def test_agent_run_tracking(self):
        from apps.core.observability.metrics import AriaMetrics
        m = AriaMetrics()

        m.record_agent_run("orchestrator", success=True)
        m.record_agent_run("orchestrator", success=True)
        m.record_agent_run("marketing", success=False)

        d = m.to_dict()
        assert d["agents"]["orchestrator"]["runs"] == 2
        assert d["agents"]["orchestrator"]["errors"] == 0
        assert d["agents"]["marketing"]["errors"] == 1

    def test_memory_tracking(self):
        from apps.core.observability.metrics import AriaMetrics
        m = AriaMetrics()

        m.record_memory_read(hit=True)
        m.record_memory_read(hit=True)
        m.record_memory_read(hit=False)
        m.record_memory_write()

        d = m.to_dict()
        assert d["memory"]["reads"] == 3
        assert d["memory"]["cache_hits"] == 2
        assert d["memory"]["cache_misses"] == 1
        assert d["memory"]["writes"] == 1

    def test_prometheus_export_format(self):
        from apps.core.observability.metrics import AriaMetrics
        m = AriaMetrics()

        m.record_income_cycle(success=True, revenue_usd=99.99)
        m.record_ai_call("groq", "llama", tokens=100, success=True)
        m.record_request(error=False)

        output = m.to_prometheus()

        # Must be parseable as Prometheus text format
        assert "aria_income_cycles_total 1.0" in output
        assert "aria_income_revenue_usd_total" in output
        assert 'aria_ai_calls_total{provider="groq"' in output
        assert "aria_requests_total 1.0" in output

        # Every metric must have a HELP and TYPE line
        for line in output.split("\n"):
            if line.startswith("aria_") and not line.startswith("#"):
                metric_name = line.split("{")[0].split(" ")[0]
                assert f"# HELP {metric_name}" in output, f"Missing HELP for {metric_name}"

    def test_singleton_pattern(self):
        from apps.core.observability.metrics import AriaMetrics
        a = AriaMetrics()
        b = AriaMetrics()
        a.record_request()
        assert b.to_dict()["requests_total"] == 1.0

    def test_thread_safety(self):
        """Concurrent increments should not lose updates."""
        import threading
        from apps.core.observability.metrics import AriaMetrics
        m = AriaMetrics()

        def _worker():
            for _ in range(100):
                m.record_request()

        threads = [threading.Thread(target=_worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert m.to_dict()["requests_total"] == 1000.0


class TestStructuredLogging:
    def test_json_output_in_production_mode(self, caplog):
        """Logger emits parseable JSON in production environment."""
        import os
        original_env = os.environ.get("ENVIRONMENT")
        try:
            os.environ["ENVIRONMENT"] = "production"
            from apps.core.observability.logging import _JSONFormatter, _TraceInjectingFilter

            record = logging.LogRecord(
                name="test.logger",
                level=logging.INFO,
                pathname="test.py",
                lineno=1,
                msg="Test message %s",
                args=("world",),
                exc_info=None,
            )
            _TraceInjectingFilter().filter(record)
            output = _JSONFormatter().format(record)
            parsed = json.loads(output)

            assert parsed["level"] == "INFO"
            assert parsed["message"] == "Test message world"
            assert parsed["logger"] == "test.logger"
            assert "ts" in parsed
            assert "trace_id" in parsed
        finally:
            if original_env is None:
                os.environ.pop("ENVIRONMENT", None)
            else:
                os.environ["ENVIRONMENT"] = original_env

    def test_extra_fields_included(self):
        from apps.core.observability.logging import _JSONFormatter, _TraceInjectingFilter

        record = logging.LogRecord(
            name="aria.income",
            level=logging.INFO,
            pathname="income.py",
            lineno=42,
            msg="Cycle complete",
            args=(),
            exc_info=None,
        )
        record.strategy = "content_pipeline"
        record.revenue = 42.50

        _TraceInjectingFilter().filter(record)
        output = _JSONFormatter().format(record)
        parsed = json.loads(output)

        assert parsed["strategy"] == "content_pipeline"
        assert parsed["revenue"] == 42.50


class TestTracingNoOp:
    def test_no_op_tracer_context_manager(self):
        from apps.core.observability.tracing import _NoOpTracer
        tracer = _NoOpTracer()

        with tracer.start_as_current_span("test_span") as span:
            span.set_attribute("key", "value")
            span.set_status("ok")

    def test_get_trace_id_without_otel(self):
        from apps.core.observability.tracing import _otel_available
        if not _otel_available:
            from apps.core.observability.tracing import get_trace_id
            assert get_trace_id() == ""

    def test_setup_tracing_idempotent(self):
        from apps.core.observability.tracing import setup_tracing, _tracer_provider
        # First call initializes
        setup_tracing()
        first_provider = _tracer_provider
        # Second call is a no-op
        setup_tracing()
        from apps.core.observability import tracing
        assert tracing._tracer_provider is first_provider
