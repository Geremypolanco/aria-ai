"""
Phase 8 tests — Arize Phoenix AI Evaluation.
Covers: CognitionTracer, AIEvaluator.
"""
from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ── Shared mock helpers ────────────────────────────────────────────────────────

def _mock_cache():
    c = MagicMock()
    c.get = AsyncMock(return_value=None)
    c.set = AsyncMock(return_value=True)
    return c


# ══════════════════════════════════════════════════════════════════════════════
# 1. COGNITION TRACER
# ══════════════════════════════════════════════════════════════════════════════

class TestCognitionTracer:

    @pytest.fixture
    def tracer(self):
        with patch("apps.evaluation.phoenix.tracer.get_cache", return_value=_mock_cache()):
            from apps.evaluation.phoenix.tracer import CognitionTracer
            t = CognitionTracer()
            # Ensure loaded state so cache mock is not called again during tests
            t._loaded = True
            return t

    @pytest.mark.asyncio
    async def test_record_trace(self, tracer):
        with patch("apps.evaluation.phoenix.tracer.get_cache", return_value=_mock_cache()):
            trace = await tracer.record(
                agent_name="test_agent",
                task_type="summarize",
                prompt="Summarize this text",
                response="This is a summary with 42 specific items mentioned",
                model="gpt-4",
                latency_ms=123.4,
            )
        assert trace.trace_id is not None
        assert len(trace.trace_id) > 0
        assert trace.agent_name == "test_agent"
        assert trace.task_type == "summarize"

    @pytest.mark.asyncio
    async def test_quality_scoring_empty(self, tracer):
        score = tracer._score_quality("")
        assert score == 0.0

    @pytest.mark.asyncio
    async def test_quality_scoring_short(self, tracer):
        score = tracer._score_quality("OK")
        # short text, no numbers, may have hedge words — base 0.5 + 0.1 hedge bonus
        assert 0.0 < score < 1.0

    @pytest.mark.asyncio
    async def test_quality_scoring_long_with_numbers(self, tracer):
        long_response = "The system processes 42 requests per second across 200 nodes. " * 5
        score = tracer._score_quality(long_response)
        # Should score higher for length + numbers
        assert score >= 0.7

    @pytest.mark.asyncio
    async def test_quality_scoring_no_hedge_words(self, tracer):
        response = "The answer is 42. This works as specified."
        score_no_hedge = tracer._score_quality(response)
        response_with_hedge = "I think the answer might be 42. I'm not sure."
        score_with_hedge = tracer._score_quality(response_with_hedge)
        assert score_no_hedge >= score_with_hedge

    @pytest.mark.asyncio
    async def test_hallucination_estimate_empty(self, tracer):
        risk = tracer._estimate_hallucination("")
        assert risk == 0.0

    @pytest.mark.asyncio
    async def test_hallucination_estimate_overconfident(self, tracer):
        low_risk = tracer._estimate_hallucination("The sky is blue on clear days.")
        high_risk = tracer._estimate_hallucination("This definitely always works 100% guaranteed and certainly never fails.")
        assert high_risk > low_risk

    @pytest.mark.asyncio
    async def test_analytics_empty(self, tracer):
        tracer._traces = []
        result = await tracer.analytics()
        assert result == {"total_traces": 0}

    @pytest.mark.asyncio
    async def test_analytics_with_data(self, tracer):
        with patch("apps.evaluation.phoenix.tracer.get_cache", return_value=_mock_cache()):
            await tracer.record("agent_a", "task_x", "prompt1", "response with 5 numbers")
            await tracer.record("agent_b", "task_y", "prompt2", "another response", success=False)

        result = await tracer.analytics()
        assert result["total_traces"] == 2
        assert "by_agent" in result
        assert "avg_latency_ms" in result
        assert "avg_quality_score" in result
        assert result["failure_rate"] == 0.5  # 1 out of 2 failed

    @pytest.mark.asyncio
    async def test_recent_traces_limit(self, tracer):
        with patch("apps.evaluation.phoenix.tracer.get_cache", return_value=_mock_cache()):
            for i in range(10):
                await tracer.record(f"agent_{i}", "task", f"prompt{i}", f"response{i}")

        recent = await tracer.recent_traces(limit=5)
        assert len(recent) <= 5


# ══════════════════════════════════════════════════════════════════════════════
# 2. AI EVALUATOR
# ══════════════════════════════════════════════════════════════════════════════

class TestAIEvaluator:

    @pytest.fixture
    def evaluator(self):
        from apps.evaluation.phoenix.evaluator import AIEvaluator
        return AIEvaluator()

    def test_evaluate_returns_result(self, evaluator):
        from apps.evaluation.phoenix.evaluator import EvaluationResult
        result = evaluator.evaluate("This is a test response.", prompt="test")
        assert isinstance(result, EvaluationResult)
        assert isinstance(result.scores, dict)
        assert len(result.scores) > 0
        assert 0.0 <= result.overall_score <= 1.0

    def test_relevance_with_matching_words(self, evaluator):
        prompt = "explain machine learning algorithms"
        content = "Machine learning algorithms learn patterns from training data to make predictions."
        result = evaluator.evaluate(content, prompt=prompt)
        assert result.scores["relevance"] > 0.5

    def test_relevance_low_when_no_overlap(self, evaluator):
        prompt = "explain quantum computing"
        content = "The weather today is sunny and warm."
        result = evaluator.evaluate(content, prompt=prompt)
        # Low overlap → lower relevance
        assert result.scores["relevance"] <= 0.7

    def test_specificity_with_numbers(self, evaluator):
        generic = "This is a good approach to consider."
        specific = "Use 3 workers, each handling 100 requests per second."
        generic_result = evaluator.evaluate(generic)
        specific_result = evaluator.evaluate(specific)
        assert specific_result.scores["specificity"] >= generic_result.scores["specificity"]

    def test_toxicity_flagging(self, evaluator):
        toxic_content = "This could harm the user."
        result = evaluator.evaluate(toxic_content)
        assert result.scores["toxicity_safe"] < 0.5

    def test_safe_content_high_toxicity_score(self, evaluator):
        safe_content = "Here is a helpful guide to getting started."
        result = evaluator.evaluate(safe_content)
        assert result.scores["toxicity_safe"] > 0.5

    def test_empty_response_flags(self, evaluator):
        result = evaluator.evaluate("")
        assert "EMPTY_RESPONSE" in result.flags

    def test_generic_content_low_specificity(self, evaluator):
        generic = "As an AI, I cannot provide specific information about this topic."
        result = evaluator.evaluate(generic)
        assert "TOO_GENERIC" in result.flags

    def test_batch_evaluate(self, evaluator):
        from apps.evaluation.phoenix.evaluator import EvaluationResult
        items = [
            {"content": "Response one with 5 examples.", "prompt": "question one"},
            {"content": "Response two with specific data: 42%.", "prompt": "question two"},
            {"content": "", "prompt": "question three"},
        ]
        results = evaluator.batch_evaluate(items)
        assert len(results) == 3
        assert all(isinstance(r, EvaluationResult) for r in results)

    def test_summary_report(self, evaluator):
        items = [
            {"content": "Excellent detailed response with 10 specific examples and actionable steps. Build and create more."},
            {"content": ""},
            {"content": "Average response. Try to do better."},
        ]
        results = evaluator.batch_evaluate(items)
        report = evaluator.summary_report(results)
        assert "avg_overall_score" in report
        assert report["total"] == 3
        assert 0.0 <= report["avg_overall_score"] <= 1.0

    def test_summary_report_empty(self, evaluator):
        report = evaluator.summary_report([])
        assert report == {"total": 0}


