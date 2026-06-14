"""
Phase 8 tests — LangGraph StateGraph workflows and DSPy prompt optimization.

Covers:
  - AgentState TypedDict structure
  - LangGraph node functions (analyze_task, create_plan, execute_step, reflect, handle_failure)
  - Workflow builder (build_cognitive_workflow) — LangGraph present and absent paths
  - CognitiveAgent.run() — workflow path and fallback path
  - CognitiveAgent.history() and summary()
  - get_cognitive_agent() singleton
  - DSPy signatures availability guard
  - PromptOptimizer.score_content() — DSPy present and absent
  - PromptOptimizer.generate_ad_copy() — DSPy present and absent
  - PromptOptimizer.plan_campaign() — fallback
  - PromptOptimizer.summary()
  - get_prompt_optimizer() singleton
"""
from __future__ import annotations

import asyncio
import sys
from types import ModuleType
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ── Shared mock helpers ────────────────────────────────────────────────────────

def _mock_ai(content: str = "AI response text") -> MagicMock:
    """Build a sync AI client mock whose .complete() is an async mock."""
    ai = MagicMock()
    response = MagicMock()
    response.success = True
    response.content = content
    ai.complete = AsyncMock(return_value=response)
    return ai


def _mock_ai_failed() -> MagicMock:
    """Build a sync AI client mock whose .complete() returns a failed response."""
    ai = MagicMock()
    response = MagicMock()
    response.success = False
    response.content = ""
    ai.complete = AsyncMock(return_value=response)
    return ai


# ══════════════════════════════════════════════════════════════════════════════
# 1. AGENT STATE
# ══════════════════════════════════════════════════════════════════════════════

class TestAgentState:
    def test_typeddict_fields(self):
        from apps.cognition.langgraph.agent_state import AgentState
        # Verify all required keys are declared in __annotations__
        annotations = AgentState.__annotations__
        for key in ("messages", "task", "context", "reasoning_steps", "plan",
                    "current_step", "result", "confidence", "iteration",
                    "max_iterations", "status"):
            assert key in annotations, f"Missing field: {key}"

    def test_annotated_list_fields(self):
        """messages and reasoning_steps must use Annotated[list, operator.add]."""
        import operator
        from typing import get_args, get_origin, get_type_hints, Annotated
        from apps.cognition.langgraph.agent_state import AgentState
        # Use get_type_hints to resolve forward refs created by 'from __future__ import annotations'
        import apps.cognition.langgraph.agent_state as _m
        hints = get_type_hints(_m.AgentState, include_extras=True)
        for field in ("messages", "reasoning_steps"):
            hint = hints[field]
            origin = get_origin(hint)
            # get_origin(Annotated[...]) returns typing.Annotated in Python 3.11
            assert origin is Annotated, f"{field} should be Annotated, got origin={origin}"
            args = get_args(hint)
            assert args[1] is operator.add, f"{field} annotation should use operator.add"

    def test_instantiate_as_dict(self):
        """AgentState can be constructed as a plain dict (TypedDict runtime)."""
        from apps.cognition.langgraph.agent_state import AgentState
        state: AgentState = {  # type: ignore[typeddict-item]
            "messages": [],
            "task": "hello",
            "context": {},
            "reasoning_steps": [],
            "plan": [],
            "current_step": 0,
            "result": "",
            "confidence": 0.0,
            "iteration": 0,
            "max_iterations": 3,
            "status": "thinking",
        }
        assert state["task"] == "hello"
        assert state["status"] == "thinking"


# ══════════════════════════════════════════════════════════════════════════════
# 2. NODE FUNCTIONS
# ══════════════════════════════════════════════════════════════════════════════

def _base_state(**overrides) -> dict:
    base = {
        "messages": [],
        "task": "write a blog post about AI",
        "context": {"audience": "developers"},
        "reasoning_steps": [],
        "plan": [],
        "current_step": 0,
        "result": "",
        "confidence": 0.0,
        "iteration": 0,
        "max_iterations": 3,
        "status": "thinking",
    }
    base.update(overrides)
    return base


class TestAnalyzeTask:
    def test_returns_reasoning_step_and_status(self):
        with patch("apps.cognition.langgraph.nodes.get_ai_client", return_value=_mock_ai("obs1\nobs2")):
            from apps.cognition.langgraph import nodes
            # reload to pick up the patch
            import importlib; importlib.reload(nodes)
            with patch("apps.cognition.langgraph.nodes.get_ai_client", return_value=_mock_ai("obs1\nobs2")):
                result = nodes.analyze_task(_base_state())
        assert "reasoning_steps" in result
        assert isinstance(result["reasoning_steps"], list)
        assert result["status"] == "planning"

    def test_no_ai_client_graceful(self):
        with patch("apps.cognition.langgraph.nodes.get_ai_client", return_value=None):
            from apps.cognition.langgraph import nodes
            result = nodes.analyze_task(_base_state())
        assert result["status"] == "planning"
        assert len(result["reasoning_steps"]) >= 1

    def test_failed_ai_response_graceful(self):
        with patch("apps.cognition.langgraph.nodes.get_ai_client", return_value=_mock_ai_failed()):
            from apps.cognition.langgraph import nodes
            result = nodes.analyze_task(_base_state())
        assert result["status"] == "planning"


class TestCreatePlan:
    def test_returns_plan_and_status(self):
        with patch("apps.cognition.langgraph.nodes.get_ai_client",
                   return_value=_mock_ai("1. Research\n2. Draft\n3. Review")):
            from apps.cognition.langgraph import nodes
            state = _base_state(reasoning_steps=["Analysis: key points"])
            result = nodes.create_plan(state)
        assert "plan" in result
        assert isinstance(result["plan"], list)
        assert len(result["plan"]) > 0
        assert result["status"] == "executing"

    def test_no_ai_client_fallback(self):
        with patch("apps.cognition.langgraph.nodes.get_ai_client", return_value=None):
            from apps.cognition.langgraph import nodes
            result = nodes.create_plan(_base_state())
        assert isinstance(result["plan"], list)
        assert result["status"] == "executing"


class TestExecuteStep:
    def test_returns_result_and_advances_step(self):
        with patch("apps.cognition.langgraph.nodes.get_ai_client",
                   return_value=_mock_ai("Step result output")):
            from apps.cognition.langgraph import nodes
            state = _base_state(plan=["Step 1: do research", "Step 2: write"])
            result = nodes.execute_step(state)
        assert "result" in result
        assert result["current_step"] == 1
        assert result["status"] == "reflecting"

    def test_no_ai_client_fallback(self):
        with patch("apps.cognition.langgraph.nodes.get_ai_client", return_value=None):
            from apps.cognition.langgraph import nodes
            state = _base_state(plan=["Step 1"])
            result = nodes.execute_step(state)
        assert result["status"] == "reflecting"
        assert isinstance(result["result"], str)


class TestReflect:
    def test_done_when_max_iterations_reached(self):
        from apps.cognition.langgraph import nodes
        state = _base_state(iteration=2, max_iterations=3, result="some output", plan=["s1"])
        result = nodes.reflect(state)
        assert result["status"] == "done"
        assert result["iteration"] == 3

    def test_continues_when_plan_steps_remain(self):
        from apps.cognition.langgraph import nodes
        state = _base_state(iteration=0, max_iterations=3, plan=["s1", "s2"], current_step=0)
        result = nodes.reflect(state)
        # Should not be "done" yet since plan steps remain
        assert result["iteration"] == 1

    def test_high_confidence_leads_to_done(self):
        with patch("apps.cognition.langgraph.nodes.get_ai_client",
                   return_value=_mock_ai("0.95")):
            from apps.cognition.langgraph import nodes
            state = _base_state(iteration=0, max_iterations=3, plan=[], current_step=0, result="good")
            result = nodes.reflect(state)
        assert result["status"] == "done"
        assert result["confidence"] >= 0.9

    def test_no_ai_graceful(self):
        with patch("apps.cognition.langgraph.nodes.get_ai_client", return_value=None):
            from apps.cognition.langgraph import nodes
            state = _base_state(plan=[], current_step=0, result="ok")
            result = nodes.reflect(state)
        assert "confidence" in result
        assert "status" in result


class TestHandleFailure:
    def test_returns_failed_status(self):
        from apps.cognition.langgraph import nodes
        state = _base_state(iteration=1, result="partial")
        result = nodes.handle_failure(state)
        assert result["status"] == "failed"
        assert "result" in result
        assert isinstance(result["result"], str)


# ══════════════════════════════════════════════════════════════════════════════
# 3. WORKFLOW BUILDER
# ══════════════════════════════════════════════════════════════════════════════

class TestBuildCognitiveWorkflow:
    def test_returns_none_when_langgraph_unavailable(self):
        """Simulate langgraph missing."""
        with patch.dict(sys.modules, {"langgraph": None, "langgraph.graph": None}):
            import importlib
            import apps.cognition.langgraph.workflow as wf_module
            # Temporarily set the flag to False
            original = wf_module._LANGGRAPH_AVAILABLE
            wf_module._LANGGRAPH_AVAILABLE = False
            try:
                result = wf_module.build_cognitive_workflow()
                assert result is None
            finally:
                wf_module._LANGGRAPH_AVAILABLE = original

    def test_returns_compiled_graph_when_langgraph_available(self):
        """When langgraph IS available, build_cognitive_workflow() returns a runnable."""
        try:
            import langgraph  # noqa: F401
        except ImportError:
            pytest.skip("langgraph not installed")

        from apps.cognition.langgraph.workflow import build_cognitive_workflow
        wf = build_cognitive_workflow()
        # If LangGraph is available, we expect a compiled graph (not None)
        assert wf is not None


# ══════════════════════════════════════════════════════════════════════════════
# 4. COGNITIVE AGENT
# ══════════════════════════════════════════════════════════════════════════════

def _make_agent(max_iterations: int = 2, use_workflow: bool = False):
    """Return a CognitiveAgent with workflow mocked out or enabled."""
    if use_workflow:
        # Return real agent (workflow may or may not be present)
        from apps.cognition.langgraph.cognitive_agent import CognitiveAgent
        return CognitiveAgent(max_iterations=max_iterations)

    from apps.cognition.langgraph.cognitive_agent import CognitiveAgent
    agent = CognitiveAgent.__new__(CognitiveAgent)
    agent.agent_id = "test-agent"
    agent.max_iterations = max_iterations
    agent._workflow = None  # force fallback
    agent._history = []
    return agent


class TestCognitiveAgentFallback:
    """Tests for the fallback path (no LangGraph workflow)."""

    @pytest.mark.asyncio
    async def test_run_fallback_success(self):
        agent = _make_agent()
        with patch("apps.cognition.langgraph.cognitive_agent.get_ai_client",
                   return_value=_mock_ai("Great blog post content")):
            result = await agent.run("Write a blog post")
        assert result["task"] == "Write a blog post"
        assert result["status"] == "done"
        assert "Great blog post content" in result["result"]

    @pytest.mark.asyncio
    async def test_run_fallback_no_ai_client(self):
        agent = _make_agent()
        with patch("apps.cognition.langgraph.cognitive_agent.get_ai_client",
                   return_value=None):
            result = await agent.run("Write a blog post")
        assert result["status"] == "failed"

    @pytest.mark.asyncio
    async def test_run_fallback_failed_response(self):
        agent = _make_agent()
        with patch("apps.cognition.langgraph.cognitive_agent.get_ai_client",
                   return_value=_mock_ai_failed()):
            result = await agent.run("Write something")
        assert result["status"] == "failed"

    @pytest.mark.asyncio
    async def test_run_stores_history(self):
        agent = _make_agent()
        with patch("apps.cognition.langgraph.cognitive_agent.get_ai_client",
                   return_value=_mock_ai("output")):
            await agent.run("task 1")
            await agent.run("task 2")
        history = agent.history()
        assert len(history) == 2

    def test_history_capped_at_50(self):
        agent = _make_agent()
        for i in range(60):
            agent._history.append({"task": f"t{i}", "status": "done", "ts": 0.0})
        assert len(agent.history()) == 50

    def test_summary_with_no_history(self):
        agent = _make_agent()
        s = agent.summary()
        assert s["total_runs"] == 0
        assert s["success_rate"] == 0.0
        assert s["langgraph_active"] is False

    def test_summary_calculates_success_rate(self):
        agent = _make_agent()
        agent._history = [
            {"task": "t1", "status": "done", "ts": 0.0},
            {"task": "t2", "status": "failed", "ts": 0.0},
            {"task": "t3", "status": "done", "ts": 0.0},
        ]
        s = agent.summary()
        assert s["total_runs"] == 3
        assert s["successful"] == 2
        assert abs(s["success_rate"] - 2 / 3) < 1e-6

    @pytest.mark.asyncio
    async def test_run_with_context(self):
        agent = _make_agent()
        with patch("apps.cognition.langgraph.cognitive_agent.get_ai_client",
                   return_value=_mock_ai("context-aware response")):
            result = await agent.run("Analyse data", context={"user": "alice", "plan": "premium"})
        assert result["status"] == "done"


class TestCognitiveAgentWorkflow:
    """Tests for the LangGraph workflow path."""

    @pytest.mark.asyncio
    async def test_run_workflow_success(self):
        """Mock a compiled workflow that returns a final_state dict."""
        final_state = {
            "result": "workflow output",
            "confidence": 0.85,
            "reasoning_steps": ["step1"],
            "plan": ["do thing"],
            "status": "done",
            "iteration": 1,
        }
        mock_workflow = MagicMock()
        mock_workflow.invoke = MagicMock(return_value=final_state)

        from apps.cognition.langgraph.cognitive_agent import CognitiveAgent
        agent = CognitiveAgent.__new__(CognitiveAgent)
        agent.agent_id = "wf-agent"
        agent.max_iterations = 3
        agent._workflow = mock_workflow
        agent._history = []

        result = await agent.run("complex task")
        assert result["status"] == "done"
        assert result["confidence"] == 0.85
        assert result["result"] == "workflow output"

    @pytest.mark.asyncio
    async def test_run_workflow_exception_returns_failed(self):
        """If workflow.invoke raises, run() returns status=failed."""
        mock_workflow = MagicMock()
        mock_workflow.invoke = MagicMock(side_effect=RuntimeError("graph error"))

        from apps.cognition.langgraph.cognitive_agent import CognitiveAgent
        agent = CognitiveAgent.__new__(CognitiveAgent)
        agent.agent_id = "wf-agent-err"
        agent.max_iterations = 3
        agent._workflow = mock_workflow
        agent._history = []

        result = await agent.run("task that fails")
        assert result["status"] == "failed"
        assert "error" in result

    def test_summary_shows_langgraph_active(self):
        mock_workflow = MagicMock()
        from apps.cognition.langgraph.cognitive_agent import CognitiveAgent
        agent = CognitiveAgent.__new__(CognitiveAgent)
        agent.agent_id = "wf-agent"
        agent.max_iterations = 3
        agent._workflow = mock_workflow
        agent._history = []
        s = agent.summary()
        assert s["langgraph_active"] is True


class TestGetCognitiveAgentSingleton:
    def test_singleton_returns_same_instance(self):
        import apps.cognition.langgraph.cognitive_agent as ca_module
        ca_module._cognitive_agent = None  # reset singleton
        agent1 = ca_module.get_cognitive_agent()
        agent2 = ca_module.get_cognitive_agent()
        assert agent1 is agent2

    def test_singleton_creates_with_agent_id(self):
        import apps.cognition.langgraph.cognitive_agent as ca_module
        ca_module._cognitive_agent = None
        agent = ca_module.get_cognitive_agent(agent_id="custom-id")
        assert agent.agent_id == "custom-id"
        ca_module._cognitive_agent = None  # cleanup


# ══════════════════════════════════════════════════════════════════════════════
# 5. DSPy SIGNATURES
# ══════════════════════════════════════════════════════════════════════════════

class TestDSpySignatures:
    def test_module_imports_without_error(self):
        """signatures.py must import even when dspy is absent."""
        # Simply import — the module itself handles the ImportError
        from apps.cognition.dspy import signatures  # noqa: F401

    def test_availability_flag_reflects_installation(self):
        from apps.cognition.dspy.signatures import _DSPY_AVAILABLE
        try:
            import dspy  # noqa: F401
            assert _DSPY_AVAILABLE is True
        except ImportError:
            assert _DSPY_AVAILABLE is False

    def test_signatures_are_none_when_dspy_missing(self):
        """When dspy is not installed, sentinels should be None."""
        from apps.cognition.dspy.signatures import _DSPY_AVAILABLE
        if not _DSPY_AVAILABLE:
            from apps.cognition.dspy.signatures import (
                AdCopywriter,
                CampaignStrategy,
                ContentQuality,
            )
            assert ContentQuality is None
            assert CampaignStrategy is None
            assert AdCopywriter is None

    def test_signatures_are_classes_when_dspy_present(self):
        from apps.cognition.dspy.signatures import _DSPY_AVAILABLE
        if not _DSPY_AVAILABLE:
            pytest.skip("dspy not installed")
        from apps.cognition.dspy.signatures import (
            AdCopywriter,
            CampaignStrategy,
            ContentQuality,
        )
        assert ContentQuality is not None
        assert CampaignStrategy is not None
        assert AdCopywriter is not None


# ══════════════════════════════════════════════════════════════════════════════
# 6. PROMPT OPTIMIZER
# ══════════════════════════════════════════════════════════════════════════════

class TestPromptOptimizerFallback:
    """Tests that cover the DSPy-unavailable fallback path."""

    @pytest.fixture
    def optimizer_no_dspy(self):
        """Return a PromptOptimizer with DSPy forced off."""
        from apps.cognition.dspy import optimizer as opt_module
        with patch.object(opt_module, "_DSPY_AVAILABLE", False):
            from apps.cognition.dspy.optimizer import PromptOptimizer
            inst = PromptOptimizer.__new__(PromptOptimizer)
            inst._available = False
            inst._optimized = {}
            inst._predictors = {}
            return inst

    @pytest.mark.asyncio
    async def test_score_content_fallback(self, optimizer_no_dspy):
        result = await optimizer_no_dspy.score_content("Great post!", "twitter")
        assert "quality_score" in result
        assert "improvement" in result
        assert result["quality_score"] == "7"

    @pytest.mark.asyncio
    async def test_generate_ad_copy_fallback(self, optimizer_no_dspy):
        result = await optimizer_no_dspy.generate_ad_copy("Widget", "developers", "google")
        assert "headline" in result
        assert "body" in result
        assert "cta" in result

    @pytest.mark.asyncio
    async def test_plan_campaign_fallback(self, optimizer_no_dspy):
        result = await optimizer_no_dspy.plan_campaign("Widget", "SMBs", "5000")
        assert "campaign_plan" in result
        assert "expected_roi" in result

    def test_summary_shows_dspy_unavailable(self, optimizer_no_dspy):
        s = optimizer_no_dspy.summary()
        assert s["dspy_available"] is False
        assert isinstance(s["optimized_modules"], list)

    def test_optimize_content_quality_returns_none_when_unavailable(self, optimizer_no_dspy):
        result = optimizer_no_dspy.optimize_content_quality([])
        assert result is None


class TestPromptOptimizerWithMockedDspy:
    """Tests that cover the DSPy-available path using a mock dspy module."""

    def _make_optimizer_with_mock_dspy(self):
        """
        Build a PromptOptimizer where _available=True and _dspy_module is patched
        so the predictor-based paths are exercised.
        """
        # Build a fake prediction result
        pred_result = MagicMock()
        pred_result.quality_score = "8"
        pred_result.improvement = "Add CTA"
        pred_result.headline = "Big Headline"
        pred_result.body = "Body text here"
        pred_result.cta = "Buy Now"
        pred_result.campaign_plan = "1. Research\n2. Launch"
        pred_result.expected_roi = "180"

        predictor = MagicMock(return_value=pred_result)

        from apps.cognition.dspy.optimizer import PromptOptimizer
        inst = PromptOptimizer.__new__(PromptOptimizer)
        inst._available = True
        inst._optimized = {}
        inst._predictors = {
            "content_quality": predictor,
            "ad_copywriter": MagicMock(return_value=pred_result),
            "campaign_strategy": MagicMock(return_value=pred_result),
        }
        return inst

    @pytest.mark.asyncio
    async def test_score_content_uses_predictor(self):
        opt = self._make_optimizer_with_mock_dspy()
        # Patch _dspy_module so the availability gate passes
        import apps.cognition.dspy.optimizer as opt_module
        fake_dspy = MagicMock()
        with patch.object(opt_module, "_dspy_module", fake_dspy):
            result = await opt.score_content("Awesome content here", "linkedin")
        assert result["quality_score"] == "8"
        assert result["improvement"] == "Add CTA"

    @pytest.mark.asyncio
    async def test_generate_ad_copy_uses_predictor(self):
        opt = self._make_optimizer_with_mock_dspy()
        import apps.cognition.dspy.optimizer as opt_module
        fake_dspy = MagicMock()
        with patch.object(opt_module, "_dspy_module", fake_dspy):
            result = await opt.generate_ad_copy("SuperWidget", "developers", "linkedin")
        assert result["headline"] == "Big Headline"
        assert result["cta"] == "Buy Now"

    @pytest.mark.asyncio
    async def test_score_content_handles_predictor_exception(self):
        from apps.cognition.dspy.optimizer import PromptOptimizer
        import apps.cognition.dspy.optimizer as opt_module
        inst = PromptOptimizer.__new__(PromptOptimizer)
        inst._available = True
        inst._optimized = {}
        broken_predictor = MagicMock(side_effect=RuntimeError("DSPy error"))
        inst._predictors = {"content_quality": broken_predictor}
        fake_dspy = MagicMock()
        with patch.object(opt_module, "_dspy_module", fake_dspy):
            result = await inst.score_content("some content", "twitter")
        # Should gracefully degrade
        assert "quality_score" in result

    @pytest.mark.asyncio
    async def test_generate_ad_copy_handles_exception(self):
        from apps.cognition.dspy.optimizer import PromptOptimizer
        import apps.cognition.dspy.optimizer as opt_module
        inst = PromptOptimizer.__new__(PromptOptimizer)
        inst._available = True
        inst._optimized = {}
        broken = MagicMock(side_effect=RuntimeError("oops"))
        inst._predictors = {"ad_copywriter": broken}
        fake_dspy = MagicMock()
        with patch.object(opt_module, "_dspy_module", fake_dspy):
            result = await inst.generate_ad_copy("Prod", "audience", "fb")
        assert "headline" in result

    def test_summary_shows_dspy_available(self):
        opt = self._make_optimizer_with_mock_dspy()
        s = opt.summary()
        assert s["dspy_available"] is True
        assert "content_quality" in s["active_predictors"]


class TestGetPromptOptimizerSingleton:
    def test_singleton_returns_same_instance(self):
        import apps.cognition.dspy.optimizer as opt_module
        opt_module._prompt_optimizer = None
        opt1 = opt_module.get_prompt_optimizer()
        opt2 = opt_module.get_prompt_optimizer()
        assert opt1 is opt2
        opt_module._prompt_optimizer = None  # cleanup

    def test_singleton_is_prompt_optimizer(self):
        import apps.cognition.dspy.optimizer as opt_module
        opt_module._prompt_optimizer = None
        from apps.cognition.dspy.optimizer import PromptOptimizer, get_prompt_optimizer
        instance = get_prompt_optimizer()
        assert isinstance(instance, PromptOptimizer)
        opt_module._prompt_optimizer = None  # cleanup
