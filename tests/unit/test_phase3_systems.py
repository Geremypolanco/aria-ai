"""
Tests for Phase 3 enterprise systems:
- Tool Intelligence Registry
- Durable Checkpoints
- ROI Engine
- Agent Hierarchy
- Reasoning Tracer (cognitive observability)

(Memory Orchestrator, Cognitive Pipeline, and Quality Controller were
removed along with their dead source modules — see the memory-system
dead-code cleanup commit.)
"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ── Tool Intelligence Registry ────────────────────────────────────────────────


class TestToolRegistry:
    @pytest.fixture
    def registry(self):
        from apps.core.tools.intelligence.tool_registry import ToolRegistry

        r = ToolRegistry()
        r._loaded = True  # skip Redis load
        return r

    def test_register_idempotent(self, registry):
        registry.register("web_search", category="web")
        registry.register("web_search", category="web")
        assert len([k for k in registry._tools if k == "web_search"]) == 1

    def test_record_call_auto_registers(self, registry):
        registry.record_call("new_tool", success=True, latency_ms=100.0)
        assert "new_tool" in registry._tools

    def test_success_rate_calculation(self, registry):
        registry.register("calc_tool")
        registry.record_call("calc_tool", success=True, latency_ms=10.0)
        registry.record_call("calc_tool", success=True, latency_ms=10.0)
        registry.record_call("calc_tool", success=False, latency_ms=10.0)
        assert abs(registry._tools["calc_tool"].success_rate - 2 / 3) < 0.01

    def test_best_tools_sorted_by_composite(self, registry):
        registry.register("fast_reliable", category="api")
        registry.register("slow_unreliable", category="api")
        for _ in range(5):
            registry.record_call("fast_reliable", success=True, latency_ms=50.0)
        for _ in range(5):
            registry.record_call("slow_unreliable", success=False, latency_ms=5000.0)
        best = registry.best_tools(category="api", min_success_rate=0.0, top_k=2)
        assert best[0].name == "fast_reliable"

    def test_failing_tools_threshold(self, registry):
        registry.register("bad_tool")
        for _ in range(5):
            registry.record_call("bad_tool", success=False, latency_ms=100.0, error="timeout")
        failing = registry.failing_tools(threshold=0.3)
        assert any(t.name == "bad_tool" for t in failing)

    def test_failing_tools_requires_min_calls(self, registry):
        registry.register("new_bad")
        registry.record_call("new_bad", success=False, latency_ms=10.0)
        registry.record_call("new_bad", success=False, latency_ms=10.0)
        failing = registry.failing_tools(threshold=0.3)
        assert not any(t.name == "new_bad" for t in failing)

    def test_error_patterns_bounded(self, registry):
        registry.register("error_tool")
        for i in range(15):
            registry.record_call("error_tool", success=False, latency_ms=10.0, error=f"error_{i}")
        assert len(registry._tools["error_tool"].error_patterns) <= 10

    def test_summary_structure(self, registry):
        registry.register("t1")
        registry.record_call("t1", success=True, latency_ms=100.0)
        s = registry.summary()
        assert "total_tools" in s
        assert "avg_success_rate" in s
        assert "most_reliable" in s

    def test_get_stats_returns_none_for_unknown(self, registry):
        assert registry.get_stats("does_not_exist") is None


# ── ROI Engine ────────────────────────────────────────────────────────────────


class TestROIEngine:
    @pytest.fixture
    def engine(self):
        from apps.core.business.roi_engine import ROIEngine

        e = ROIEngine()
        e._loaded = True
        return e

    @pytest.mark.asyncio
    async def test_score_opportunity_computes_roi(self, engine):
        with patch.object(engine, "_persist", new=AsyncMock()):
            opp = await engine.score_opportunity(
                name="Content Marketing",
                category="content",
                estimated_revenue_usd=1000.0,
                estimated_effort_hours=10.0,
                risk_level=0.2,
                time_to_revenue_days=7,
                confidence=0.8,
            )
        assert opp.roi_score > 0
        assert opp.opportunity_id.startswith("opp_")

    @pytest.mark.asyncio
    async def test_rank_opportunities_sorted_desc(self, engine):
        with patch.object(engine, "_persist", new=AsyncMock()):
            await engine.score_opportunity("Low ROI", "content", 100.0, 100.0, confidence=0.5)
            await engine.score_opportunity("High ROI", "content", 5000.0, 2.0, confidence=0.9)
            ranked = await engine.rank_opportunities()
        assert ranked[0].name == "High ROI"

    @pytest.mark.asyncio
    async def test_rank_by_category_filter(self, engine):
        with patch.object(engine, "_persist", new=AsyncMock()):
            await engine.score_opportunity("Content A", "content", 500.0, 5.0)
            await engine.score_opportunity("Shopify B", "ecommerce", 500.0, 5.0)
            content_ranked = await engine.rank_opportunities(category="content")
        assert all(o.category == "content" for o in content_ranked)

    @pytest.mark.asyncio
    async def test_record_outcome_updates_confidence(self, engine):
        with patch.object(engine, "_persist", new=AsyncMock()):
            opp = await engine.score_opportunity("Test", "general", 200.0, 4.0, confidence=0.7)
            before = opp.confidence
            await engine.record_outcome(opp.opportunity_id, actual_revenue=200.0, success=True)
        assert engine._opportunities[opp.opportunity_id].confidence > before

    @pytest.mark.asyncio
    async def test_portfolio_summary_structure(self, engine):
        with patch.object(engine, "_persist", new=AsyncMock()):
            await engine.score_opportunity("A", "content", 100.0, 5.0)
        summary = await engine.get_portfolio_summary()
        assert "total_opportunities" in summary
        assert "total_estimated_revenue_usd" in summary
        assert "avg_roi_score" in summary

    def test_compute_roi_zero_effort_clamped(self):
        from apps.core.business.roi_engine import _compute_roi

        roi = _compute_roi(1000.0, 0.0, 0.5, 7, 0.8)
        assert 0 <= roi <= 1000.0

    @pytest.mark.asyncio
    async def test_recommend_next_action_returns_string(self, engine):
        with patch.object(engine, "_persist", new=AsyncMock()):
            await engine.score_opportunity("Best Bet", "affiliate", 2000.0, 3.0, confidence=0.9)
        rec = await engine.recommend_next_action()
        assert isinstance(rec, str)
        assert "Best Bet" in rec


# ── Agent Hierarchy ───────────────────────────────────────────────────────────


class TestAgentHierarchy:
    @pytest.fixture
    def hierarchy(self):
        from apps.core.agents.hierarchy.agent_hierarchy import AgentHierarchy

        return AgentHierarchy()

    def test_register_creates_node(self, hierarchy):
        from apps.core.agents.hierarchy.agent_hierarchy import AgentRole

        hierarchy.register("exec", "Executive", AgentRole.EXECUTIVE)
        node = hierarchy.get_node("exec")
        assert node is not None
        assert node.role == AgentRole.EXECUTIVE

    def test_register_links_parent_child(self, hierarchy):
        from apps.core.agents.hierarchy.agent_hierarchy import AgentRole

        hierarchy.register("exec", "Executive", AgentRole.EXECUTIVE)
        hierarchy.register("dir", "Director", AgentRole.DIRECTOR, parent_id="exec")
        exec_node = hierarchy.get_node("exec")
        assert "dir" in exec_node.child_ids

    def test_get_children_filters_by_role(self, hierarchy):
        from apps.core.agents.hierarchy.agent_hierarchy import AgentRole

        hierarchy.register("exec", "Exec", AgentRole.EXECUTIVE)
        hierarchy.register("dir1", "Dir1", AgentRole.DIRECTOR, parent_id="exec")
        hierarchy.register("mgr1", "Mgr1", AgentRole.MANAGER, parent_id="exec")
        dirs = hierarchy.get_children("exec", role=AgentRole.DIRECTOR)
        assert len(dirs) == 1 and dirs[0].agent_id == "dir1"

    def test_best_delegate_prefers_capable_agent(self, hierarchy):
        from apps.core.agents.hierarchy.agent_hierarchy import AgentRole

        hierarchy.register("exec", "Exec", AgentRole.EXECUTIVE)
        hierarchy.register(
            "income_spec",
            "Income",
            AgentRole.SPECIALIST,
            capabilities=["income", "revenue"],
            parent_id="exec",
        )
        hierarchy.register(
            "content_spec",
            "Content",
            AgentRole.SPECIALIST,
            capabilities=["content", "blog"],
            parent_id="exec",
        )
        best = hierarchy.best_delegate("exec", "generate income from revenue streams")
        assert best is not None
        assert best.agent_id == "income_spec"

    @pytest.mark.asyncio
    async def test_delegate_executes_handler(self, hierarchy):
        from apps.core.agents.hierarchy.agent_hierarchy import AgentRole, DelegationStatus

        async def my_handler(task, ctx):
            return f"handled: {task}"

        hierarchy.register("exec", "Exec", AgentRole.EXECUTIVE)
        hierarchy.register(
            "worker", "Worker", AgentRole.WORKER, parent_id="exec", handler=my_handler
        )
        rec = await hierarchy.delegate("exec", "worker", "do the thing")
        assert rec.status == DelegationStatus.DONE
        assert rec.result == "handled: do the thing"

    @pytest.mark.asyncio
    async def test_delegate_to_unknown_agent_rejected(self, hierarchy):
        from apps.core.agents.hierarchy.agent_hierarchy import AgentRole, DelegationStatus

        hierarchy.register("exec", "Exec", AgentRole.EXECUTIVE)
        rec = await hierarchy.delegate("exec", "nonexistent", "task")
        assert rec.status == DelegationStatus.REJECTED

    @pytest.mark.asyncio
    async def test_cascade_routes_to_specialist(self, hierarchy):
        from apps.core.agents.hierarchy.agent_hierarchy import AgentRole, DelegationStatus

        async def spec_handler(task, ctx):
            return "specialist result"

        hierarchy.register("exec", "Exec", AgentRole.EXECUTIVE)
        hierarchy.register("dir", "Dir", AgentRole.DIRECTOR, parent_id="exec")
        hierarchy.register(
            "spec",
            "Spec",
            AgentRole.SPECIALIST,
            capabilities=["write", "content"],
            parent_id="dir",
            handler=spec_handler,
        )
        rec = await hierarchy.cascade("dir", "write content article")
        assert rec.status == DelegationStatus.DONE

    def test_get_chain_of_command(self, hierarchy):
        from apps.core.agents.hierarchy.agent_hierarchy import AgentRole

        hierarchy.register("ceo", "CEO", AgentRole.EXECUTIVE)
        hierarchy.register("vp", "VP", AgentRole.DIRECTOR, parent_id="ceo")
        hierarchy.register("mgr", "Mgr", AgentRole.MANAGER, parent_id="vp")
        chain = hierarchy.get_chain_of_command("mgr")
        assert [n.agent_id for n in chain] == ["ceo", "vp", "mgr"]

    def test_summary_counts_agents_and_delegations(self, hierarchy):
        from apps.core.agents.hierarchy.agent_hierarchy import AgentRole

        hierarchy.register("a1", "A1", AgentRole.EXECUTIVE)
        hierarchy.register("a2", "A2", AgentRole.SPECIALIST, parent_id="a1")
        s = hierarchy.summary()
        assert s["total_agents"] == 2
        assert s["active_agents"] == 2

    def test_reporting_structure_has_roots(self, hierarchy):
        from apps.core.agents.hierarchy.agent_hierarchy import AgentRole

        hierarchy.register("root_a", "Root A", AgentRole.EXECUTIVE)
        structure = hierarchy.reporting_structure()
        assert len(structure["roots"]) == 1


# ── Reasoning Tracer ──────────────────────────────────────────────────────────


class TestReasoningTracer:
    @pytest.fixture
    def tracer(self):
        from apps.core.observability.cognition.reasoning_tracer import ReasoningTracer

        return ReasoningTracer(max_traces=100)

    def test_start_trace_returns_trace(self, tracer):
        t = tracer.start_trace("Is AI profitable?")
        assert t.trace_id.startswith("rt_")
        assert t.question == "Is AI profitable?"

    def test_finish_sets_conclusion(self, tracer):
        t = tracer.start_trace("Question?")
        t.add_step(1, "Initial thought", uncertainty=0.3)
        t.finish("Yes, it is profitable.", confidence=0.85)
        assert t.conclusion == "Yes, it is profitable."
        assert t.confidence == 0.85
        assert t.finished_at is not None

    def test_hallucination_risk_computed_on_finish(self, tracer):
        t = tracer.start_trace("Question?")
        t.add_step(1, "Analysis", uncertainty=0.8)
        t.finish("Definitely, certainly, guaranteed 100% profit!", confidence=0.4)
        assert t.hallucination_risk > 0.0
        assert "certainty_overstatement" in t.hallucination_signals

    def test_high_risk_traces_filter(self, tracer):
        t = tracer.start_trace("Risky?")
        t.add_step(1, "vague", uncertainty=0.9)
        t.finish("Definitely 100% certain guaranteed success!", confidence=0.2)
        high_risk = tracer.high_risk_traces(threshold=0.5)
        assert t in high_risk

    def test_max_traces_eviction(self, tracer):
        from apps.core.observability.cognition.reasoning_tracer import ReasoningTracer

        small_tracer = ReasoningTracer(max_traces=5)
        for i in range(7):
            small_tracer.start_trace(f"Question {i}")
        assert len(small_tracer._traces) <= 5

    def test_summary_structure(self, tracer):
        t = tracer.start_trace("Test?")
        t.finish("answer", confidence=0.8)
        s = tracer.summary()
        assert "total_traces" in s
        assert "avg_confidence" in s
        assert "avg_hallucination_risk" in s
