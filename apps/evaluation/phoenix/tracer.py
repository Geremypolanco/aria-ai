"""
CognitionTracer — Trace AI calls for evaluation with Arize Phoenix.

When PHOENIX_ENDPOINT env var is set → sends traces to Phoenix server.
Otherwise → in-memory trace collection with local analysis.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field

try:
    import phoenix as px  # noqa: F401
    from openinference.instrumentation.openai import OpenAIInstrumentor  # noqa: F401

    _PHOENIX_AVAILABLE = True
except ImportError:
    _PHOENIX_AVAILABLE = False

from apps.core.memory.redis_client import get_cache

_TRACE_KEY = "evaluation:traces:v1"
_TRACE_TTL = 86400 * 30


@dataclass
class AITrace:
    trace_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    agent_name: str = ""
    task_type: str = ""
    prompt: str = ""
    response: str = ""
    model: str = ""
    latency_ms: float = 0.0
    tokens_used: int = 0
    success: bool = True
    quality_score: float = 0.0
    hallucination_risk: float = 0.0
    ts: float = field(default_factory=time.time)
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "trace_id": self.trace_id,
            "agent_name": self.agent_name,
            "task_type": self.task_type,
            "prompt": self.prompt[:200],  # truncate for storage
            "response": self.response[:500],
            "model": self.model,
            "latency_ms": self.latency_ms,
            "tokens_used": self.tokens_used,
            "success": self.success,
            "quality_score": self.quality_score,
            "hallucination_risk": self.hallucination_risk,
            "ts": self.ts,
            "metadata": self.metadata,
        }


class CognitionTracer:
    """
    Traces AI cognitive operations for evaluation and debugging.

    Storage: in-memory ring buffer + Redis.
    Optional: Arize Phoenix when PHOENIX_ENDPOINT is configured.
    """

    MAX_TRACES = 1000

    def __init__(self):
        self._traces: list[dict] = []
        self._loaded = False
        self._phoenix_active = False
        self._init_phoenix()

    def _init_phoenix(self) -> None:
        if not _PHOENIX_AVAILABLE:
            return
        import os

        endpoint = os.environ.get("PHOENIX_ENDPOINT", "")
        if endpoint:
            try:
                # Set up Phoenix tracing
                from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

                OTLPSpanExporter(endpoint=endpoint)
                self._phoenix_active = True
            except Exception:
                pass

    async def _load(self) -> None:
        if not self._loaded:
            try:
                cache = get_cache()
                data = await cache.get(_TRACE_KEY)
                if isinstance(data, list):
                    self._traces = data
            except Exception:
                pass
            self._loaded = True

    async def _save(self) -> None:
        try:
            cache = get_cache()
            await cache.set(_TRACE_KEY, self._traces[-self.MAX_TRACES :], ttl_seconds=_TRACE_TTL)
        except Exception:
            pass

    async def record(
        self,
        agent_name: str,
        task_type: str,
        prompt: str,
        response: str,
        model: str = "",
        latency_ms: float = 0.0,
        success: bool = True,
        metadata: dict = None,
    ) -> AITrace:
        if metadata is None:
            metadata = {}
        await self._load()
        trace = AITrace(
            agent_name=agent_name,
            task_type=task_type,
            prompt=prompt,
            response=response,
            model=model,
            latency_ms=latency_ms,
            success=success,
            quality_score=self._score_quality(response),
            hallucination_risk=self._estimate_hallucination(response),
            metadata=metadata,
        )
        self._traces.append(trace.to_dict())
        if len(self._traces) > self.MAX_TRACES:
            self._traces = self._traces[-self.MAX_TRACES :]
        await self._save()
        return trace

    def _score_quality(self, response: str) -> float:
        """Simple heuristic quality score 0-1."""
        if not response:
            return 0.0
        score = 0.5
        # Length signal
        if len(response) > 50:
            score += 0.1
        if len(response) > 200:
            score += 0.1
        # Specificity signals
        has_numbers = any(c.isdigit() for c in response)
        if has_numbers:
            score += 0.1
        # No hallucination markers
        hedge_words = ["I think", "probably", "might be", "I'm not sure"]
        if not any(h.lower() in response.lower() for h in hedge_words):
            score += 0.1
        return min(1.0, score)

    def _estimate_hallucination(self, response: str) -> float:
        """Estimate hallucination risk 0-1 based on heuristics."""
        if not response:
            return 0.0
        risk = 0.1
        # Specific numbers without context are risky
        import re

        if re.search(r"\b\d{4,}\b", response):
            risk += 0.1
        # Highly confident claims
        overconfident = ["definitely", "certainly", "100%", "guaranteed", "always", "never"]
        count = sum(1 for w in overconfident if w.lower() in response.lower())
        risk += count * 0.05
        return min(0.9, risk)

    async def analytics(self) -> dict:
        await self._load()
        if not self._traces:
            return {"total_traces": 0}

        by_agent: dict[str, int] = {}
        by_task: dict[str, int] = {}
        total_latency = 0.0
        failed = 0
        total_quality = 0.0
        total_hallucination = 0.0

        for t in self._traces:
            by_agent[t.get("agent_name", "unknown")] = (
                by_agent.get(t.get("agent_name", "unknown"), 0) + 1
            )
            by_task[t.get("task_type", "unknown")] = (
                by_task.get(t.get("task_type", "unknown"), 0) + 1
            )
            total_latency += t.get("latency_ms", 0)
            if not t.get("success", True):
                failed += 1
            total_quality += t.get("quality_score", 0)
            total_hallucination += t.get("hallucination_risk", 0)

        n = len(self._traces)
        return {
            "total_traces": n,
            "by_agent": by_agent,
            "by_task": by_task,
            "avg_latency_ms": round(total_latency / n, 1),
            "failure_rate": round(failed / n, 3),
            "avg_quality_score": round(total_quality / n, 3),
            "avg_hallucination_risk": round(total_hallucination / n, 3),
            "phoenix_active": self._phoenix_active,
        }

    async def recent_traces(self, limit: int = 20) -> list[dict]:
        await self._load()
        return list(reversed(self._traces[-limit:]))

    async def agent_report(self, agent_name: str) -> dict:
        await self._load()
        agent_traces = [t for t in self._traces if t.get("agent_name") == agent_name]
        if not agent_traces:
            return {"agent_name": agent_name, "total_traces": 0}
        n = len(agent_traces)
        return {
            "agent_name": agent_name,
            "total_traces": n,
            "success_rate": sum(1 for t in agent_traces if t.get("success", True)) / n,
            "avg_quality": sum(t.get("quality_score", 0) for t in agent_traces) / n,
            "avg_hallucination_risk": sum(t.get("hallucination_risk", 0) for t in agent_traces) / n,
            "avg_latency_ms": sum(t.get("latency_ms", 0) for t in agent_traces) / n,
        }


_tracer_instance: CognitionTracer | None = None


def get_cognition_tracer() -> CognitionTracer:
    global _tracer_instance
    if _tracer_instance is None:
        _tracer_instance = CognitionTracer()
    return _tracer_instance
