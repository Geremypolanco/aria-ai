"""
Unit tests for the cognitive core — planner and reasoning engine.

These tests verify:
  - ARIAPlanner decomposes goals into executable task DAGs
  - Plan execution follows dependency order
  - ReasoningEngine produces structured reasoning results
  - Both modules degrade gracefully without an AI client
"""
from __future__ import annotations

import asyncio
import json
import pytest
from unittest.mock import AsyncMock, MagicMock


class TestARIAPlanner:
    @pytest.fixture
    def planner(self):
        from apps.core.cognition.planner import ARIAPlanner
        return ARIAPlanner()

    @pytest.fixture
    def mock_ai(self):
        ai = AsyncMock()
        ai.complete_json = AsyncMock(return_value={
            "reasoning": "Breaking goal into parallel research and action steps.",
            "tasks": [
                {
                    "title": "Research market",
                    "description": "Analyze target market trends",
                    "tool": "web_search",
                    "tool_args": {"query": "AI tools market 2024"},
                    "depends_on": [],
                    "priority": 1,
                },
                {
                    "title": "Generate content",
                    "description": "Create landing page copy",
                    "tool": "generate_content",
                    "tool_args": {"type": "landing_page"},
                    "depends_on": [0],
                    "priority": 2,
                },
            ],
        })
        return ai

    @pytest.mark.asyncio
    async def test_create_plan_with_ai(self, planner, mock_ai):
        plan = await planner.create_plan(
            "Launch an AI tools Shopify store",
            context={"budget": 0},
            ai_client=mock_ai,
        )

        assert plan.id
        assert len(plan.tasks) == 2
        assert plan.tasks[0].tool == "web_search"
        assert plan.tasks[1].depends_on == [plan.tasks[0].id]
        assert plan.reasoning

    @pytest.mark.asyncio
    async def test_create_plan_without_ai_fallback(self, planner):
        plan = await planner.create_plan(
            "Do something useful",
            ai_client=None,
        )

        assert plan.id
        assert len(plan.tasks) == 1
        assert plan.tasks[0].title

    @pytest.mark.asyncio
    async def test_task_dependency_order(self, planner, mock_ai):
        plan = await planner.create_plan("Test goal", ai_client=mock_ai)

        execution_order = []

        async def executor(task):
            execution_order.append(task.id)
            return {"success": True, "output": "done"}

        events = []
        async for event in planner.execute_plan(plan, executor):
            events.append(event["event"])

        assert "plan_done" in events
        # Task 0 (research) must run before Task 1 (generate — depends on 0)
        t0_id = plan.tasks[0].id
        t1_id = plan.tasks[1].id
        assert execution_order.index(t0_id) < execution_order.index(t1_id)

    @pytest.mark.asyncio
    async def test_plan_completes_on_success(self, planner, mock_ai):
        plan = await planner.create_plan("Success test", ai_client=mock_ai)

        async def always_succeeds(task):
            return {"success": True}

        events = []
        async for event in planner.execute_plan(plan, always_succeeds):
            events.append(event)

        final = events[-1]
        assert final["event"] == "plan_done"
        assert final["plan"]["status"] == "done"

    @pytest.mark.asyncio
    async def test_plan_fails_when_all_retries_exhausted(self, planner):
        from apps.core.cognition.planner import Plan, PlanTask, PlanStatus, TaskStatus

        # Create a plan with a single task that always fails
        plan = Plan(
            id="fail-test",
            goal="Always fail",
            context={},
            tasks=[PlanTask(
                id="fail-test-0",
                title="Impossible task",
                description="This will fail",
                tool="none",
                tool_args={},
                depends_on=[],
            )],
        )
        # Set max retries to 0 by pre-exhausting attempts
        plan.replan_count = 3  # MAX_REPLAN

        async def always_fails(task):
            return {"success": False, "error": "Intentional failure"}

        events = []
        async for event in planner.execute_plan(plan, always_fails):
            events.append(event)

        assert any(e["event"] == "failed" for e in events)

    def test_plan_ready_tasks_respects_dependencies(self):
        from apps.core.cognition.planner import Plan, PlanTask, TaskStatus

        tasks = [
            PlanTask(id="p-0", title="A", description="", tool="t", tool_args={}, depends_on=[]),
            PlanTask(id="p-1", title="B", description="", tool="t", tool_args={}, depends_on=["p-0"]),
            PlanTask(id="p-2", title="C", description="", tool="t", tool_args={}, depends_on=["p-0"]),
        ]
        plan = Plan(id="p", goal="test", context={}, tasks=tasks)

        # Initially only task 0 is ready
        ready_ids = {t.id for t in plan.ready_tasks}
        assert ready_ids == {"p-0"}

        # After task 0 completes, tasks 1 and 2 become ready
        tasks[0].status = TaskStatus.DONE
        ready_ids = {t.id for t in plan.ready_tasks}
        assert ready_ids == {"p-1", "p-2"}

    def test_plan_progress_calculation(self):
        from apps.core.cognition.planner import Plan, PlanTask, TaskStatus

        tasks = [
            PlanTask(id=f"t{i}", title=f"Task {i}", description="", tool="t", tool_args={}, depends_on=[])
            for i in range(4)
        ]
        plan = Plan(id="p", goal="test", context={}, tasks=tasks)

        assert plan.progress_pct() == 0.0
        tasks[0].status = TaskStatus.DONE
        tasks[1].status = TaskStatus.DONE
        assert plan.progress_pct() == 50.0

    def test_plan_serialization_roundtrip(self):
        from apps.core.cognition.planner import Plan, PlanTask

        task = PlanTask(
            id="t0", title="Test", description="desc", tool="web_search",
            tool_args={"q": "test"}, depends_on=[], priority=2,
        )
        plan = Plan(id="abc", goal="Test goal", context={"x": 1}, tasks=[task])
        serialized = plan.to_dict()
        restored = Plan.from_dict(serialized)

        assert restored.id == plan.id
        assert restored.goal == plan.goal
        assert len(restored.tasks) == 1
        assert restored.tasks[0].tool == "web_search"


class TestReasoningEngine:
    @pytest.fixture
    def mock_ai(self):
        ai = AsyncMock()

        # think → steps
        # critique → critique
        # revise → synthesis
        call_count = 0

        async def complete_json_side_effect(system="", user=""):
            nonlocal call_count
            call_count += 1
            if "Generate a structured chain" in system or "chain of thought" in system.lower():
                return {
                    "steps": [
                        {
                            "thought": "Market analysis shows high demand for AI tools",
                            "evidence": ["Google Trends data", "App Store rankings"],
                            "uncertainty": 0.2,
                            "leads_to": "There is market opportunity",
                        },
                        {
                            "thought": "ARIA has content generation capability already",
                            "evidence": ["income_loop.py has content_pipeline strategy"],
                            "uncertainty": 0.1,
                            "leads_to": "Low execution risk",
                        },
                    ]
                }
            elif "self-critique" in system.lower() or "critique" in system.lower():
                return {
                    "issues": ["Missing competitive analysis"],
                    "strengths": ["Evidence-based reasoning"],
                    "confidence_adjustment": -0.05,
                    "recommendation": "Add competitor research step",
                }
            else:
                return {
                    "conclusion": "Launch a content-first AI tools store targeting developers.",
                    "uncertainty_flags": ["Conversion rate unknown", "Ad costs unclear"],
                    "action": "Create a landing page with 3 AI tool listings this week.",
                    "confidence_delta": 0.05,
                }

        ai.complete_json = AsyncMock(side_effect=complete_json_side_effect)
        return ai

    @pytest.fixture
    def engine(self, mock_ai):
        from apps.core.cognition.reasoning_engine import ReasoningEngine
        return ReasoningEngine(ai_client=mock_ai)

    @pytest.mark.asyncio
    async def test_reason_produces_structured_result(self, engine):
        result = await engine.reason(
            question="Should ARIA launch a Shopify store for AI tools?",
            context={"revenue": 0, "skills": ["content", "ai"]},
        )

        assert result.id
        assert result.question
        assert len(result.steps) >= 1
        assert result.conclusion
        assert 0.0 <= result.confidence <= 1.0
        assert result.action_recommendation
        assert result.reasoning_time_ms >= 0

    @pytest.mark.asyncio
    async def test_reason_without_ai_returns_fallback(self):
        from apps.core.cognition.reasoning_engine import ReasoningEngine
        engine = ReasoningEngine(ai_client=None)

        result = await engine.reason("Should I do X?")

        assert result.confidence == 0.0
        assert "unavailable" in result.conclusion.lower()
        assert len(result.steps) == 1
        assert result.steps[0].uncertainty == 1.0

    @pytest.mark.asyncio
    async def test_confidence_adjusted_by_critique(self, engine):
        result = await engine.reason(
            "Test question",
            critique_rounds=1,
        )
        # Critique adjusts confidence — should not be exactly base
        assert result.confidence > 0.0

    @pytest.mark.asyncio
    async def test_high_uncertainty_steps_lower_confidence(self):
        from apps.core.cognition.reasoning_engine import ReasoningEngine, ReasoningStep

        ai = AsyncMock()
        ai.complete_json = AsyncMock(side_effect=[
            # think: all high uncertainty
            {
                "steps": [
                    {"thought": "Unsure", "evidence": [], "uncertainty": 0.9, "leads_to": "Guess"},
                    {"thought": "Very unsure", "evidence": [], "uncertainty": 0.95, "leads_to": "Guess"},
                ]
            },
            # critique
            {"issues": ["Too uncertain"], "strengths": [], "confidence_adjustment": -0.1, "recommendation": ""},
            # revise
            {"conclusion": "Low confidence answer", "uncertainty_flags": ["everything"], "action": "none", "confidence_delta": 0.0},
        ])
        engine = ReasoningEngine(ai_client=ai)
        result = await engine.reason("Unanswerable question", critique_rounds=1)

        assert result.confidence < 0.3

    @pytest.mark.asyncio
    async def test_result_to_dict_is_json_serializable(self, engine):
        result = await engine.reason("Can I serialize this?")
        d = result.to_dict()
        serialized = json.dumps(d)  # must not raise
        assert isinstance(json.loads(serialized), dict)

    @pytest.mark.asyncio
    async def test_history_is_maintained(self, engine):
        await engine.reason("First question")
        await engine.reason("Second question")

        history = await engine.get_history(limit=10)
        assert len(history) == 2
        assert history[0]["question"] == "First question"
        assert history[1]["question"] == "Second question"

    def test_is_high_confidence_threshold(self):
        from apps.core.cognition.reasoning_engine import ReasoningResult, ReasoningStep

        step = ReasoningStep(step=0, thought="t", evidence=[], uncertainty=0.1, leads_to="x")
        base = ReasoningResult(
            id="x", question="q", context={}, steps=[step], critiques=[],
            conclusion="c", confidence=0.8, uncertainty_flags=[],
            action_recommendation="a", reasoning_time_ms=100,
        )
        assert base.is_high_confidence

        base.confidence = 0.6
        assert not base.is_high_confidence

    def test_summary_includes_confidence_label(self):
        from apps.core.cognition.reasoning_engine import ReasoningResult, ReasoningStep

        step = ReasoningStep(step=0, thought="t", evidence=[], uncertainty=0.0, leads_to="x")
        result = ReasoningResult(
            id="x", question="q", context={}, steps=[step], critiques=[],
            conclusion="The answer is yes.", confidence=0.9, uncertainty_flags=[],
            action_recommendation="Do it now.", reasoning_time_ms=50,
        )
        summary = result.summary
        assert "HIGH" in summary
        assert "The answer is yes." in summary
        assert "Do it now." in summary
