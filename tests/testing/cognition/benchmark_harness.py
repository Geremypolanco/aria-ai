"""
Cognitive benchmark harness — deterministic scenarios for reasoning quality.

Provides:
  - ReasoningBenchmark: named scenarios with expected properties
  - HallucinationRegression: test that known-bad patterns are detected
  - BenchmarkRunner: executes suites, computes pass rates, stores baselines

Scenarios are deterministic: same inputs always produce same expected structure.
What varies (and is tested) is the quality of the AI-generated content.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional


@dataclass
class ScenarioResult:
    scenario_id: str
    passed: bool
    score: float
    details: dict[str, Any] = field(default_factory=dict)
    duration_ms: float = 0.0
    error: Optional[str] = None


@dataclass
class BenchmarkSuite:
    name: str
    scenarios: list["Scenario"] = field(default_factory=list)

    def add(self, scenario: "Scenario") -> "BenchmarkSuite":
        self.scenarios.append(scenario)
        return self


@dataclass
class Scenario:
    id: str
    description: str
    input_text: str
    expected_properties: dict[str, Any]
    evaluator: Callable[[Any], ScenarioResult]


@dataclass
class BenchmarkReport:
    suite_name: str
    total: int
    passed: int
    failed: int
    avg_score: float
    results: list[ScenarioResult]
    duration_ms: float

    @property
    def pass_rate(self) -> float:
        return self.passed / self.total if self.total else 0.0

    def to_dict(self) -> dict:
        return {
            "suite_name": self.suite_name,
            "total": self.total,
            "passed": self.passed,
            "failed": self.failed,
            "pass_rate": round(self.pass_rate, 3),
            "avg_score": round(self.avg_score, 3),
            "duration_ms": round(self.duration_ms, 1),
            "results": [
                {"id": r.scenario_id, "passed": r.passed, "score": round(r.score, 3),
                 "details": r.details, "error": r.error}
                for r in self.results
            ],
        }


class BenchmarkRunner:
    def __init__(self) -> None:
        self._baselines: dict[str, float] = {}
        self._history: list[BenchmarkReport] = []

    async def run(self, suite: BenchmarkSuite, subject: Any) -> BenchmarkReport:
        t0 = time.monotonic()
        results = []

        for scenario in suite.scenarios:
            ts = time.monotonic()
            try:
                result = scenario.evaluator(subject)
            except Exception as exc:
                result = ScenarioResult(
                    scenario_id=scenario.id,
                    passed=False,
                    score=0.0,
                    error=str(exc),
                )
            result.duration_ms = (time.monotonic() - ts) * 1000
            results.append(result)

        passed = sum(1 for r in results if r.passed)
        avg_score = sum(r.score for r in results) / max(len(results), 1)

        report = BenchmarkReport(
            suite_name=suite.name,
            total=len(results),
            passed=passed,
            failed=len(results) - passed,
            avg_score=avg_score,
            results=results,
            duration_ms=(time.monotonic() - t0) * 1000,
        )
        self._history.append(report)
        return report

    def set_baseline(self, suite_name: str, pass_rate: float) -> None:
        self._baselines[suite_name] = pass_rate

    def regression_detected(self, report: BenchmarkReport, tolerance: float = 0.05) -> bool:
        baseline = self._baselines.get(report.suite_name)
        if baseline is None:
            return False
        return report.pass_rate < baseline - tolerance

    def history(self) -> list[dict]:
        return [r.to_dict() for r in self._history]


# ── Built-in hallucination regression suite ───────────────────────────────────

def build_hallucination_suite() -> BenchmarkSuite:
    """
    Scenarios where the ReasoningTracer MUST detect hallucination signals.
    Tests that known-bad patterns are consistently flagged.
    """
    from apps.core.observability.cognition.reasoning_tracer import ReasoningTracer

    suite = BenchmarkSuite("hallucination_regression")

    def make_evaluator(text: str, expected_signal: str) -> Callable:
        def evaluate(tracer: ReasoningTracer) -> ScenarioResult:
            trace = tracer.start_trace(f"Test: {text[:50]}")
            trace.add_step(1, text, uncertainty=0.5)
            trace.finish(text, confidence=0.8)
            detected = expected_signal in trace.hallucination_signals
            return ScenarioResult(
                scenario_id=expected_signal,
                passed=detected,
                score=1.0 if detected else 0.0,
                details={"detected_signals": trace.hallucination_signals, "expected": expected_signal},
            )
        return evaluate

    suite.add(Scenario(
        id="certainty_overstatement",
        description="Detects overconfident language",
        input_text="This strategy is definitely guaranteed to succeed 100% of the time",
        expected_properties={"signal": "certainty_overstatement"},
        evaluator=make_evaluator(
            "This strategy is definitely guaranteed to succeed 100% of the time",
            "certainty_overstatement",
        ),
    ))

    suite.add(Scenario(
        id="temporal_confusion",
        description="Detects references to unstated recency",
        input_text="Recently in 2023 the market showed strong growth patterns",
        expected_properties={"signal": "temporal_confusion"},
        evaluator=make_evaluator(
            "Recently in 2023 the market showed strong growth patterns",
            "temporal_confusion",
        ),
    ))

    suite.add(Scenario(
        id="unsupported_specifics",
        description="Detects unattributed specific numbers",
        input_text="According to the study this earns exactly $5000 per month",
        expected_properties={"signal": "unsupported_specifics"},
        evaluator=make_evaluator(
            "According to the study this earns exactly $5000 per month",
            "unsupported_specifics",
        ),
    ))

    return suite


def build_rule_engine_suite() -> BenchmarkSuite:
    """Tests that the rule engine correctly enforces deterministic governance."""
    from apps.core.deterministic.rule_engine import get_rule_engine

    suite = BenchmarkSuite("rule_engine_governance")

    def budget_cap_test(engine: Any) -> ScenarioResult:
        result = engine.first_match({"daily_spend_usd": 60, "budget_cap_usd": 50}, tags=["budget"])
        blocked = result is not None and result.get("blocked") is True
        return ScenarioResult("budget_cap", blocked, 1.0 if blocked else 0.0)

    def reliability_gate_test(engine: Any) -> ScenarioResult:
        result = engine.first_match({"tool_success_rate": 0.1}, tags=["tools"])
        skipped = result is not None and result.get("skip_tool") is True
        return ScenarioResult("tool_reliability", skipped, 1.0 if skipped else 0.0)

    def depth_limit_test(engine: Any) -> ScenarioResult:
        result = engine.first_match({"delegation_depth": 5}, tags=["agents"])
        blocked = result is not None and result.get("blocked") is True
        return ScenarioResult("depth_limit", blocked, 1.0 if blocked else 0.0)

    suite.add(Scenario("budget_cap", "Budget cap enforced", "", {"blocked": True}, budget_cap_test))
    suite.add(Scenario("tool_reliability", "Failing tools gated", "", {"skip": True}, reliability_gate_test))
    suite.add(Scenario("depth_limit", "Depth limit enforced", "", {"blocked": True}, depth_limit_test))

    return suite


_runner: Optional[BenchmarkRunner] = None


def get_benchmark_runner() -> BenchmarkRunner:
    global _runner
    if _runner is None:
        _runner = BenchmarkRunner()
    return _runner
