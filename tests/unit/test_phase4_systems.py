"""
Tests for Phase 4 enterprise systems:
- Event schemas and bus
- Platform abstractions (cache, AI)
- Deterministic rule engine and constraints
- Tiered memory (HOT/WARM)
- Central Executive Agent
- Business Intelligence Telemetry
- Benchmark harness
"""
from __future__ import annotations

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ── Event Schemas ─────────────────────────────────────────────────────────────

class TestAriaEvent:
    def test_event_has_required_fields(self):
        from apps.core.events.schemas import AriaEvent, EventType
        ev = AriaEvent(event_type=EventType.SYSTEM_STARTUP, payload={"msg": "ok"})
        assert ev.event_id
        assert ev.correlation_id
        assert ev.ts > 0
        assert ev.version == "1.0"

    def test_event_is_immutable(self):
        from apps.core.events.schemas import AriaEvent, EventType
        ev = AriaEvent(event_type=EventType.FACT_STORED, payload={})
        with pytest.raises((AttributeError, TypeError)):
            ev.event_id = "changed"

    def test_derive_inherits_correlation(self):
        from apps.core.events.schemas import AriaEvent, EventType
        parent = AriaEvent(event_type=EventType.REASONING_STARTED, payload={})
        child = parent.derive(EventType.REASONING_COMPLETED, {"result": "done"})
        assert child.correlation_id == parent.correlation_id
        assert child.causation_id == parent.event_id

    def test_serialization_roundtrip(self):
        from apps.core.events.schemas import AriaEvent, EventType
        ev = AriaEvent(
            event_type=EventType.REVENUE_RECORDED,
            payload={"amount": 100.0, "source": "shopify"},
            source="business",
        )
        d = ev.to_dict()
        restored = AriaEvent.from_dict(d)
        assert restored.event_id == ev.event_id
        assert restored.event_type == EventType.REVENUE_RECORDED
        assert restored.payload["amount"] == 100.0

    def test_event_type_enum_values_are_strings(self):
        from apps.core.events.schemas import EventType
        for et in EventType:
            assert isinstance(et.value, str)
            assert "." in et.value


# ── Event Bus ─────────────────────────────────────────────────────────────────

class TestEventBus:
    @pytest.fixture
    def bus(self):
        from apps.core.events.bus import EventBus
        return EventBus()

    @pytest.mark.asyncio
    async def test_subscribe_and_receive(self, bus):
        from apps.core.events.schemas import AriaEvent, EventType
        received = []

        async def handler(ev: AriaEvent):
            received.append(ev)

        bus.subscribe(EventType.FACT_STORED, handler)
        ev = AriaEvent(event_type=EventType.FACT_STORED, payload={"fact": "test"})

        with patch.object(bus, "_persist", new=AsyncMock()):
            await bus.publish(ev)

        assert len(received) == 1
        assert received[0].payload["fact"] == "test"

    @pytest.mark.asyncio
    async def test_wildcard_handler_receives_all(self, bus):
        from apps.core.events.schemas import AriaEvent, EventType
        received = []

        async def catch_all(ev):
            received.append(ev.event_type)

        bus.subscribe_all(catch_all)
        with patch.object(bus, "_persist", new=AsyncMock()):
            await bus.publish(AriaEvent(event_type=EventType.FACT_STORED, payload={}))
            await bus.publish(AriaEvent(event_type=EventType.AGENT_DELEGATED, payload={}))

        assert EventType.FACT_STORED in received
        assert EventType.AGENT_DELEGATED in received

    @pytest.mark.asyncio
    async def test_failed_handler_goes_to_dlq(self, bus):
        from apps.core.events.schemas import AriaEvent, EventType

        async def bad_handler(ev):
            raise ValueError("intentional failure")

        bus.subscribe(EventType.TASK_FAILED, bad_handler)
        ev = AriaEvent(event_type=EventType.TASK_FAILED, payload={})

        with patch.object(bus, "_persist", new=AsyncMock()), \
             patch.object(bus, "_send_to_dlq", new=AsyncMock()) as mock_dlq:
            await bus.publish(ev)
            assert mock_dlq.called

    @pytest.mark.asyncio
    async def test_unsubscribe_removes_handler(self, bus):
        from apps.core.events.schemas import AriaEvent, EventType
        calls = []

        async def handler(ev):
            calls.append(ev)

        bus.subscribe(EventType.SYSTEM_STARTUP, handler)
        bus.unsubscribe(EventType.SYSTEM_STARTUP, handler)

        with patch.object(bus, "_persist", new=AsyncMock()):
            await bus.publish(AriaEvent(event_type=EventType.SYSTEM_STARTUP, payload={}))

        assert len(calls) == 0

    def test_stats_structure(self, bus):
        s = bus.stats()
        assert "published" in s
        assert "delivered" in s
        assert "failed" in s


# ── Platform Cache Abstraction ────────────────────────────────────────────────

class TestMemoryCacheProvider:
    @pytest.fixture
    def cache(self):
        from apps.core.platform.cache import MemoryCacheProvider
        return MemoryCacheProvider()

    @pytest.mark.asyncio
    async def test_set_and_get(self, cache):
        await cache.set("key1", {"value": 42})
        result = await cache.get("key1")
        assert result == {"value": 42}

    @pytest.mark.asyncio
    async def test_get_missing_key_returns_none(self, cache):
        assert await cache.get("nonexistent") is None

    @pytest.mark.asyncio
    async def test_delete_removes_key(self, cache):
        await cache.set("to_delete", "data")
        await cache.delete("to_delete")
        assert await cache.get("to_delete") is None

    @pytest.mark.asyncio
    async def test_exists_true_for_set_key(self, cache):
        await cache.set("exists_key", "yes")
        assert await cache.exists("exists_key") is True

    @pytest.mark.asyncio
    async def test_increment_starts_from_zero(self, cache):
        val = await cache.increment("counter")
        assert val == 1
        val2 = await cache.increment("counter")
        assert val2 == 2

    @pytest.mark.asyncio
    async def test_ttl_expiry(self, cache):
        import time
        await cache.set("expires", "data", ttl_seconds=1)
        # Manually expire by setting past timestamp
        cache._store["expires"] = ("data", time.time() - 2)
        assert await cache.get("expires") is None

    def test_clear_removes_all(self, cache):
        import asyncio
        asyncio.get_event_loop().run_until_complete(cache.set("k1", "v1"))
        cache.clear()
        assert len(cache._store) == 0


# ── Deterministic Rule Engine ─────────────────────────────────────────────────

class TestRuleEngine:
    @pytest.fixture
    def engine(self):
        from apps.core.deterministic.rule_engine import RuleEngine
        return RuleEngine()

    def test_add_rule_and_evaluate(self, engine):
        engine.add_rule(
            "test_rule",
            "desc",
            condition=lambda ctx: ctx.get("x", 0) > 5,
            action=lambda ctx: "triggered",
        )
        result = engine.evaluate({"x": 10})
        assert result.matched
        assert result.first_result == "triggered"

    def test_no_match_returns_empty(self, engine):
        engine.add_rule("r1", "d", lambda ctx: False, lambda ctx: "nope")
        result = engine.evaluate({"x": 1})
        assert not result.matched

    def test_priority_ordering(self, engine):
        results = []
        engine.add_rule("low_prio", "d", lambda ctx: True, lambda ctx: results.append("low") or "low", priority=100)
        engine.add_rule("high_prio", "d", lambda ctx: True, lambda ctx: results.append("high") or "high", priority=10)
        engine.evaluate({})
        assert results[0] == "high"

    def test_stop_on_first(self, engine):
        engine.add_rule("r1", "d", lambda ctx: True, lambda ctx: "first", priority=1)
        engine.add_rule("r2", "d", lambda ctx: True, lambda ctx: "second", priority=2)
        result = engine.evaluate({}, stop_on_first=True)
        assert len(result.matches) == 1

    def test_tag_filtering(self, engine):
        engine.add_rule("income_rule", "d", lambda ctx: True, lambda ctx: "income", tags=["income"])
        engine.add_rule("safety_rule", "d", lambda ctx: True, lambda ctx: "safety", tags=["safety"])
        result = engine.evaluate({}, tags=["income"])
        assert len(result.matches) == 1
        assert result.first_result == "income"

    def test_disable_rule(self, engine):
        engine.add_rule("r1", "d", lambda ctx: True, lambda ctx: "should not run")
        engine.disable("r1")
        result = engine.evaluate({})
        assert not result.matched

    def test_remove_rule(self, engine):
        engine.add_rule("r1", "d", lambda ctx: True, lambda ctx: "x")
        engine.remove_rule("r1")
        assert engine.rule_count() == 0

    def test_threshold_rule_factory(self):
        from apps.core.deterministic.rule_engine import threshold_rule, RuleEngine
        rule = threshold_rule("rev_check", "revenue", ">", 100.0, lambda ctx: "high_rev")
        engine = RuleEngine()
        engine._rules.append(rule)
        assert engine.first_match({"revenue": 150}) == "high_rev"
        assert engine.first_match({"revenue": 50}) is None

    def test_pattern_rule_factory(self):
        from apps.core.deterministic.rule_engine import pattern_rule, RuleEngine
        rule = pattern_rule("income_detect", "task", r"income|revenue|earn", lambda ctx: "income_task")
        engine = RuleEngine()
        engine._rules.append(rule)
        assert engine.first_match({"task": "generate revenue from Shopify"}) == "income_task"
        assert engine.first_match({"task": "write a blog post"}) is None

    def test_aria_rules_budget_cap(self):
        from apps.core.deterministic.rule_engine import build_aria_rules
        engine = build_aria_rules()
        result = engine.first_match({"daily_spend_usd": 55, "budget_cap_usd": 50}, tags=["budget"])
        assert result is not None
        assert result.get("blocked") is True

    def test_aria_rules_depth_limit(self):
        from apps.core.deterministic.rule_engine import build_aria_rules
        engine = build_aria_rules()
        result = engine.first_match({"delegation_depth": 5}, tags=["agents"])
        assert result is not None
        assert result.get("blocked") is True


# ── Constraint Validators ─────────────────────────────────────────────────────

class TestConstraints:
    def test_require_str_valid(self):
        from apps.core.deterministic.constraints import require_str
        r = require_str("hello", "name")
        assert r.valid

    def test_require_str_too_short(self):
        from apps.core.deterministic.constraints import require_str
        r = require_str("", "name", min_len=1)
        assert not r.valid

    def test_require_float_out_of_range(self):
        from apps.core.deterministic.constraints import require_float
        r = require_float(-1.0, "revenue", min_val=0.0)
        assert not r.valid

    def test_require_in_valid(self):
        from apps.core.deterministic.constraints import require_in
        r = require_in("content", {"content", "ecommerce"}, "category")
        assert r.valid

    def test_require_in_invalid(self):
        from apps.core.deterministic.constraints import require_in
        r = require_in("unknown", {"content", "ecommerce"}, "category")
        assert not r.valid

    def test_validate_opportunity_input_full(self):
        from apps.core.deterministic.constraints import validate_opportunity_input
        r = validate_opportunity_input({
            "name": "Test Opp", "category": "content",
            "estimated_revenue_usd": 500.0, "estimated_effort_hours": 10.0,
            "risk_level": 0.3, "confidence": 0.8,
        })
        assert r.valid

    def test_validate_opportunity_input_bad_category(self):
        from apps.core.deterministic.constraints import validate_opportunity_input
        r = validate_opportunity_input({
            "name": "T", "category": "invalid_cat",
            "estimated_revenue_usd": 500.0, "estimated_effort_hours": 10.0,
            "risk_level": 0.3, "confidence": 0.8,
        })
        assert not r.valid

    def test_constraint_result_merge(self):
        from apps.core.deterministic.constraints import ConstraintResult
        ok = ConstraintResult(True)
        err = ConstraintResult(False, [{"field": "x", "message": "bad"}])
        merged = ok.merge(err)
        assert not merged.valid
        assert len(merged.violations) == 1

    def test_raise_if_invalid(self):
        from apps.core.deterministic.constraints import ConstraintResult, ConstraintViolation
        r = ConstraintResult(False, [{"field": "x", "message": "bad x"}])
        with pytest.raises(ConstraintViolation):
            r.raise_if_invalid()


# ── Tiered Memory ─────────────────────────────────────────────────────────────

class TestTieredMemory:
    @pytest.fixture
    def mem(self):
        from apps.core.memory.tiering.tiered_memory import TieredMemory
        return TieredMemory()

    @pytest.mark.asyncio
    async def test_store_and_retrieve_hot(self, mem):
        with patch.object(mem._warm, "put", new=AsyncMock()):
            item_id = await mem.store("ARIA is an autonomous AI", category="system")
        item = await mem.retrieve(item_id)
        assert item is not None
        assert item.content == "ARIA is an autonomous AI"

    @pytest.mark.asyncio
    async def test_search_finds_by_keyword(self, mem):
        with patch.object(mem._warm, "put", new=AsyncMock()), \
             patch.object(mem._warm, "search", new=AsyncMock(return_value=[])):
            await mem.store("Shopify revenue strategy works", category="business")
            await mem.store("Unrelated medical knowledge", category="general")
            results = await mem.search("revenue strategy")
        assert len(results) >= 1
        assert any("revenue" in r.content.lower() for r in results)

    @pytest.mark.asyncio
    async def test_search_category_filter(self, mem):
        with patch.object(mem._warm, "put", new=AsyncMock()), \
             patch.object(mem._warm, "search", new=AsyncMock(return_value=[])):
            await mem.store("Business fact", category="business")
            await mem.store("System fact", category="system")
            results = await mem.search("fact", category="business")
        assert all(r.category == "business" for r in results)

    def test_hot_tier_lru_eviction(self):
        from apps.core.memory.tiering.tiered_memory import HotTier, MemoryItem
        import time
        hot = HotTier(capacity=3)
        now = time.time()
        for i in range(4):
            item = MemoryItem(
                id=f"item_{i}", content=f"Content {i}", category="test",
                source="aria", confidence=0.8, importance=0.5,
                ts=now, ts_iso="2026-01-01T00:00:00Z",
            )
            hot.put(item)
        assert hot.size() <= 3

    def test_hot_tier_search(self):
        from apps.core.memory.tiering.tiered_memory import HotTier, MemoryItem
        import time
        hot = HotTier(capacity=10)
        now = time.time()
        for term in ["alpha", "beta", "gamma"]:
            hot.put(MemoryItem(
                id=f"id_{term}", content=f"Fact about {term}", category="test",
                source="aria", confidence=0.8, importance=0.5,
                ts=now, ts_iso="2026-01-01T00:00:00Z",
            ))
        results = hot.search("alpha")
        assert len(results) == 1
        assert "alpha" in results[0].content

    def test_memory_item_tier_score_recency(self):
        from apps.core.memory.tiering.tiered_memory import MemoryItem
        import time
        recent = MemoryItem("r", "content", "cat", "src", 0.9, 0.9, time.time(), "now")
        old = MemoryItem("o", "content", "cat", "src", 0.9, 0.9, time.time() - 86400 * 10, "old")
        assert recent.tier_score() > old.tier_score()

    def test_summary_structure(self, mem):
        s = mem.summary()
        assert "hot_size" in s
        assert "write_count" in s
        assert "hot_hit_rate" in s


# ── Executive Agent ───────────────────────────────────────────────────────────

class TestExecutiveAgent:
    @pytest.fixture
    def agent(self):
        from apps.core.agents.executive.executive_agent import ExecutiveAgent
        return ExecutiveAgent()

    @pytest.mark.asyncio
    async def test_submit_executes_handler(self, agent):
        async def income_handler(task):
            return f"executed: {task.task}"

        agent.register_handler("income", income_handler)
        task = await agent.submit("generate income from Shopify")
        assert task.result is not None

    @pytest.mark.asyncio
    async def test_submit_routes_to_correct_domain(self, agent):
        calls = []

        async def income_h(task):
            calls.append("income")

        async def content_h(task):
            calls.append("content")

        agent.register_handler("income", income_h)
        agent.register_handler("content", content_h)

        await agent.submit("earn revenue from affiliate marketing")
        assert "income" in calls
        assert "content" not in calls

    @pytest.mark.asyncio
    async def test_depth_limit_rejects(self, agent):
        from apps.core.agents.executive.executive_agent import TaskStatus, TaskPriority
        task = await agent.submit("deep task", depth=5)
        assert task.status == TaskStatus.REJECTED

    @pytest.mark.asyncio
    async def test_deduplication_within_window(self, agent):
        from apps.core.agents.executive.executive_agent import TaskStatus

        async def noop(t):
            return "ok"

        agent.register_handler("default", noop)
        t1 = await agent.submit("same task content")
        t2 = await agent.submit("same task content")
        assert t2.status in (TaskStatus.CANCELLED, TaskStatus.DONE)

    @pytest.mark.asyncio
    async def test_task_classification_income(self, agent):
        domain = agent._classify("generate revenue from shopify products")
        assert domain == "income"

    @pytest.mark.asyncio
    async def test_task_classification_content(self, agent):
        domain = agent._classify("write a blog article about AI")
        assert domain == "content"

    @pytest.mark.asyncio
    async def test_budget_exhausted_rejects(self, agent):
        from apps.core.agents.executive.executive_agent import TaskStatus, ExecutionBudget
        exhausted = ExecutionBudget(max_time_seconds=0.0)
        task = await agent.submit("some task", budget=exhausted)
        assert task.status == TaskStatus.REJECTED

    def test_summary_structure(self, agent):
        s = agent.summary()
        assert "task_counts" in s
        assert "active_tasks" in s
        assert "registered_domains" in s

    @pytest.mark.asyncio
    async def test_delegate_to_domain(self, agent):
        from apps.core.agents.executive.executive_agent import TaskStatus

        async def ops_h(t):
            return "ops done"

        agent.register_handler("ops", ops_h)
        child = await agent.delegate("deploy monitoring service", to_domain="ops")
        assert child.status == TaskStatus.DONE
        assert child.result == "ops done"


# ── Business Intelligence Telemetry ──────────────────────────────────────────

class TestBITelemetry:
    @pytest.fixture
    def bi(self):
        from apps.core.business.intelligence.bi_telemetry import BITelemetry
        b = BITelemetry()
        b._loaded = True
        return b

    @pytest.mark.asyncio
    async def test_record_workflow_returns_id(self, bi):
        with patch.object(bi, "_persist", new=AsyncMock()):
            wid = await bi.record_workflow(
                workflow_type="income_cycle", agent_id="income_agent",
                strategy="shopify", revenue_usd=150.0, cost_usd=2.0,
                duration_ms=5000.0, success=True,
            )
        assert wid.startswith("wf_")

    @pytest.mark.asyncio
    async def test_report_aggregates_revenue(self, bi):
        with patch.object(bi, "_persist", new=AsyncMock()):
            await bi.record_workflow("income", "a1", "shopify", 100.0, 1.0, success=True)
            await bi.record_workflow("income", "a1", "content", 50.0, 1.0, success=True)
            report = await bi.report(window_hours=24)
        assert report["revenue_usd"] == pytest.approx(150.0)
        assert report["total_workflows"] == 2

    @pytest.mark.asyncio
    async def test_report_filters_by_window(self, bi):
        import time
        with patch.object(bi, "_persist", new=AsyncMock()):
            await bi.record_workflow("income", "a1", "shopify", 100.0, success=True)
        # Manually set timestamp to outside window
        bi._workflows[-1].ts = time.time() - 48 * 3600
        report = await bi.report(window_hours=1)
        assert report["total_workflows"] == 0

    @pytest.mark.asyncio
    async def test_report_agent_productivity(self, bi):
        with patch.object(bi, "_persist", new=AsyncMock()):
            await bi.record_workflow("income", "agent_a", "shopify", 200.0, success=True)
            await bi.record_workflow("income", "agent_b", "content", 50.0, success=False)
            report = await bi.report(window_hours=24)
        assert "by_agent" in report
        assert "agent_a" in report["by_agent"]

    @pytest.mark.asyncio
    async def test_report_tool_attribution(self, bi):
        with patch.object(bi, "_persist", new=AsyncMock()):
            await bi.record_workflow("income", "a1", "shopify", 300.0, success=True,
                                     tools_used=["web_search", "content_gen"])
            report = await bi.report(window_hours=24)
        assert "tool_revenue_attribution" in report

    def test_summary_empty(self, bi):
        s = bi.summary()
        assert s["total_workflows"] == 0

    @pytest.mark.asyncio
    async def test_workflow_profit_calculation(self, bi):
        with patch.object(bi, "_persist", new=AsyncMock()):
            wid = await bi.record_workflow("income", "a1", "shopify", 100.0, cost_usd=30.0, success=True)
        rec = bi._workflows[-1]
        assert rec.profit_usd == pytest.approx(70.0)
        assert rec.roi_multiple == pytest.approx(100.0 / 30.0)


# ── Benchmark Harness ─────────────────────────────────────────────────────────

class TestBenchmarkHarness:
    @pytest.mark.asyncio
    async def test_hallucination_suite_runs(self):
        from tests.testing.cognition.benchmark_harness import build_hallucination_suite, BenchmarkRunner
        from apps.core.observability.cognition.reasoning_tracer import ReasoningTracer

        suite = build_hallucination_suite()
        runner = BenchmarkRunner()
        tracer = ReasoningTracer()
        report = await runner.run(suite, tracer)

        assert report.total == 3
        assert report.pass_rate >= 0.5  # at least 50% of hallucination signals detected

    @pytest.mark.asyncio
    async def test_rule_engine_suite_runs(self):
        from tests.testing.cognition.benchmark_harness import build_rule_engine_suite, BenchmarkRunner
        from apps.core.deterministic.rule_engine import build_aria_rules

        suite = build_rule_engine_suite()
        runner = BenchmarkRunner()
        engine = build_aria_rules()
        report = await runner.run(suite, engine)

        assert report.total == 3
        assert report.pass_rate == 1.0  # all deterministic governance rules must pass

    @pytest.mark.asyncio
    async def test_regression_detection(self):
        from tests.testing.cognition.benchmark_harness import BenchmarkRunner, BenchmarkSuite, Scenario, ScenarioResult
        runner = BenchmarkRunner()
        suite = BenchmarkSuite("test_suite")
        suite.add(Scenario("s1", "d", "", {}, evaluator=lambda _: ScenarioResult("s1", True, 1.0)))
        runner.set_baseline("test_suite", 0.9)

        # Simulate a passing report
        report = await runner.run(suite, None)
        assert not runner.regression_detected(report, tolerance=0.2)

    def test_benchmark_report_to_dict(self):
        from tests.testing.cognition.benchmark_harness import BenchmarkReport, ScenarioResult
        report = BenchmarkReport(
            suite_name="test", total=2, passed=1, failed=1,
            avg_score=0.5, results=[
                ScenarioResult("s1", True, 1.0),
                ScenarioResult("s2", False, 0.0),
            ],
            duration_ms=100.0,
        )
        d = report.to_dict()
        assert d["pass_rate"] == 0.5
        assert len(d["results"]) == 2
