"""Cognitive observability: reasoning traces, confidence tracking, hallucination signals."""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional


@dataclass
class ReasoningTrace:
    trace_id: str
    question: str
    started_at: str
    finished_at: Optional[str] = None
    duration_ms: float = 0.0
    steps: list[dict] = field(default_factory=list)
    conclusion: str = ""
    confidence: float = 0.0
    hallucination_signals: list[str] = field(default_factory=list)
    hallucination_risk: float = 0.0

    def add_step(self, step_num: int, thought: str, uncertainty: float) -> None:
        self.steps.append({
            "step": step_num,
            "thought": thought,
            "uncertainty": uncertainty,
            "ts": datetime.now(timezone.utc).isoformat(),
        })

    def finish(self, conclusion: str, confidence: float) -> None:
        self.conclusion = conclusion
        self.confidence = confidence
        self.finished_at = datetime.now(timezone.utc).isoformat()
        self.hallucination_signals = _detect_hallucination_signals(conclusion, self.steps)
        self.hallucination_risk = _compute_hallucination_risk(
            confidence, self.hallucination_signals, self.steps
        )

    def to_dict(self) -> dict:
        return {
            "trace_id": self.trace_id,
            "question": self.question,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_ms": self.duration_ms,
            "step_count": len(self.steps),
            "conclusion": self.conclusion,
            "confidence": self.confidence,
            "hallucination_signals": self.hallucination_signals,
            "hallucination_risk": self.hallucination_risk,
            "steps": self.steps,
        }


_HALLUCINATION_PATTERNS = [
    ("certainty_overstatement", ["definitely", "certainly", "always", "never", "guaranteed", "100%"]),
    ("unsupported_specifics", ["$", "exactly", "precisely", "according to", "the study shows"]),
    ("temporal_confusion", ["yesterday", "last year", "in 2023", "recently", "currently"]),
    ("entity_fabrication", ["the company", "the user said", "as mentioned"]),
]


def _detect_hallucination_signals(conclusion: str, steps: list[dict]) -> list[str]:
    signals = []
    combined_text = conclusion + " ".join(s.get("thought", "") for s in steps)
    combined_lower = combined_text.lower()
    for signal_name, keywords in _HALLUCINATION_PATTERNS:
        if any(kw in combined_lower for kw in keywords):
            signals.append(signal_name)
    if len(steps) < 2 and len(conclusion) > 200:
        signals.append("long_conclusion_few_steps")
    return signals


def _compute_hallucination_risk(confidence: float, signals: list[str], steps: list[dict]) -> float:
    base_risk = 1.0 - confidence
    signal_penalty = len(signals) * 0.08
    avg_uncertainty = sum(s.get("uncertainty", 0.5) for s in steps) / max(len(steps), 1)
    risk = base_risk * 0.4 + signal_penalty + avg_uncertainty * 0.3
    return round(min(1.0, max(0.0, risk)), 4)


class ReasoningTracer:
    def __init__(self, max_traces: int = 500) -> None:
        self._traces: dict[str, ReasoningTrace] = {}
        self._max_traces = max_traces

    def start_trace(self, question: str) -> ReasoningTrace:
        trace = ReasoningTrace(
            trace_id=f"rt_{uuid.uuid4().hex[:10]}",
            question=question,
            started_at=datetime.now(timezone.utc).isoformat(),
        )
        if len(self._traces) >= self._max_traces:
            oldest = min(self._traces.keys(), key=lambda k: self._traces[k].started_at)
            del self._traces[oldest]
        self._traces[trace.trace_id] = trace
        return trace

    def get_trace(self, trace_id: str) -> Optional[ReasoningTrace]:
        return self._traces.get(trace_id)

    def high_risk_traces(self, threshold: float = 0.6) -> list[ReasoningTrace]:
        return [t for t in self._traces.values() if t.hallucination_risk >= threshold]

    def low_confidence_traces(self, threshold: float = 0.5) -> list[ReasoningTrace]:
        return [t for t in self._traces.values() if t.confidence < threshold and t.finished_at]

    def summary(self) -> dict:
        finished = [t for t in self._traces.values() if t.finished_at]
        if not finished:
            return {"total_traces": 0, "completed": 0}
        avg_conf = sum(t.confidence for t in finished) / len(finished)
        avg_risk = sum(t.hallucination_risk for t in finished) / len(finished)
        high_risk = sum(1 for t in finished if t.hallucination_risk >= 0.6)
        return {
            "total_traces": len(self._traces),
            "completed": len(finished),
            "avg_confidence": round(avg_conf, 3),
            "avg_hallucination_risk": round(avg_risk, 3),
            "high_risk_count": high_risk,
            "high_risk_rate": round(high_risk / len(finished), 3),
        }

    def recent(self, n: int = 20) -> list[dict]:
        traces = sorted(self._traces.values(), key=lambda t: t.started_at, reverse=True)
        return [t.to_dict() for t in traces[:n]]


_tracer: Optional[ReasoningTracer] = None


def get_reasoning_tracer() -> ReasoningTracer:
    global _tracer
    if _tracer is None:
        _tracer = ReasoningTracer()
    return _tracer
