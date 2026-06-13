"""
Tests for procedural and temporal memory layers.
"""
from __future__ import annotations

import asyncio
import time
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, patch


class TestProceduralMemory:
    @pytest.fixture
    def mem(self):
        from apps.core.memory.procedural.procedural_memory import ProceduralMemory
        return ProceduralMemory()

    @pytest.fixture
    def sample_steps(self):
        from apps.core.memory.procedural.procedural_memory import ProcedureStep
        return [
            ProcedureStep(0, "web_search", {"q": "trending topics"}, "topic list"),
            ProcedureStep(1, "generate_content", {"type": "article"}, "draft"),
            ProcedureStep(2, "publish_content", {"platform": "devto"}, "url"),
        ]

    @pytest.mark.asyncio
    async def test_store_returns_id(self, mem, sample_steps):
        with patch.object(mem, "_persist", new=AsyncMock()):
            proc_id = await mem.store("publish_blog", "publish.*blog", sample_steps)
        assert isinstance(proc_id, str)
        assert proc_id.startswith("proc_")

    @pytest.mark.asyncio
    async def test_retrieve_by_pattern_match(self, mem, sample_steps):
        with patch.object(mem, "_persist", new=AsyncMock()):
            await mem.store("publish_blog", "publish.*blog|write.*article", sample_steps)
            proc = await mem.retrieve("write an article about AI")
        assert proc is not None
        assert proc.name == "publish_blog"

    @pytest.mark.asyncio
    async def test_retrieve_returns_none_for_no_match(self, mem, sample_steps):
        with patch.object(mem, "_persist", new=AsyncMock()):
            await mem.store("publish_blog", "publish.*blog", sample_steps)
            proc = await mem.retrieve("run income cycle")
        assert proc is None

    @pytest.mark.asyncio
    async def test_record_execution_increments_counters(self, mem, sample_steps):
        with patch.object(mem, "_persist", new=AsyncMock()):
            proc_id = await mem.store("test_proc", "test", sample_steps)
            await mem.record_execution(proc_id, success=True, revenue=50.0, duration_ms=1000)
            await mem.record_execution(proc_id, success=False)

        proc = mem._procedures[proc_id]
        assert proc.execution_count == 2
        assert proc.success_count == 1
        assert proc.total_revenue_generated == 50.0

    @pytest.mark.asyncio
    async def test_success_rate_calculation(self, mem, sample_steps):
        with patch.object(mem, "_persist", new=AsyncMock()):
            proc_id = await mem.store("test_proc", "test", sample_steps)
            await mem.record_execution(proc_id, success=True)
            await mem.record_execution(proc_id, success=True)
            await mem.record_execution(proc_id, success=False)

        proc = mem._procedures[proc_id]
        assert abs(proc.success_rate - 2 / 3) < 0.01

    @pytest.mark.asyncio
    async def test_is_trusted_requires_min_executions(self, mem, sample_steps):
        with patch.object(mem, "_persist", new=AsyncMock()):
            proc_id = await mem.store("new_proc", "new", sample_steps)
            # Only 2 executions — below MIN_EXECUTIONS_TO_TRUST=3
            await mem.record_execution(proc_id, success=True)
            await mem.record_execution(proc_id, success=True)

        assert not mem._procedures[proc_id].is_trusted

        with patch.object(mem, "_persist", new=AsyncMock()):
            await mem.record_execution(proc_id, success=True)

        assert mem._procedures[proc_id].is_trusted

    @pytest.mark.asyncio
    async def test_utility_score_higher_for_successful_procedures(self, mem, sample_steps):
        with patch.object(mem, "_persist", new=AsyncMock()):
            p1_id = await mem.store("good_proc", "good", sample_steps)
            p2_id = await mem.store("bad_proc", "bad", sample_steps)

            for _ in range(5):
                await mem.record_execution(p1_id, success=True, revenue=20.0)
            for _ in range(5):
                await mem.record_execution(p2_id, success=False)

        p1 = mem._procedures[p1_id]
        p2 = mem._procedures[p2_id]
        assert p1.utility_score() > p2.utility_score()

    @pytest.mark.asyncio
    async def test_prune_removes_low_success_rate(self, mem, sample_steps):
        from apps.core.memory.procedural.procedural_memory import MIN_EXECUTIONS_TO_TRUST
        with patch.object(mem, "_persist", new=AsyncMock()):
            proc_id = await mem.store("failing_proc", "failing", sample_steps)
            # Run enough executions to hit prune threshold
            for _ in range(MIN_EXECUTIONS_TO_TRUST):
                await mem.record_execution(proc_id, success=False)

            pruned = await mem.prune_failing_procedures(min_success_rate=0.5)

        assert pruned == 1
        assert proc_id not in mem._procedures

    def test_weakest_step_returns_lowest_success_rate(self):
        from apps.core.memory.procedural.procedural_memory import Procedure, ProcedureStep
        from datetime import datetime, timezone
        steps = [
            ProcedureStep(0, "step_a", {}, "out", failure_count=0, success_count=10),
            ProcedureStep(1, "step_b", {}, "out", failure_count=8, success_count=2),
            ProcedureStep(2, "step_c", {}, "out", failure_count=0, success_count=5),
        ]
        proc = Procedure(
            id="p1", name="test", goal_pattern="test",
            steps=steps, created_at=datetime.now(timezone.utc).isoformat(),
        )
        weakest = proc.weakest_step()
        assert weakest is not None
        assert weakest.step == 1

    def test_procedure_serialization_roundtrip(self):
        from apps.core.memory.procedural.procedural_memory import Procedure, ProcedureStep
        from datetime import datetime, timezone
        proc = Procedure(
            id="p_test",
            name="test_procedure",
            goal_pattern="test.*procedure",
            steps=[
                ProcedureStep(0, "web_search", {"q": "test"}, "results",
                              failure_count=1, success_count=9),
            ],
            created_at=datetime.now(timezone.utc).isoformat(),
            execution_count=10,
            success_count=9,
            total_revenue_generated=100.0,
        )
        d = proc.to_dict()
        restored = Procedure.from_dict(d)
        assert restored.id == proc.id
        assert restored.execution_count == 10
        assert len(restored.steps) == 1
        assert restored.steps[0].success_count == 9

    def test_avg_revenue_per_run(self):
        from apps.core.memory.procedural.procedural_memory import Procedure
        from datetime import datetime, timezone
        proc = Procedure(
            id="p1", name="rev_test", goal_pattern="rev",
            steps=[], created_at=datetime.now(timezone.utc).isoformat(),
            execution_count=4, total_revenue_generated=200.0,
        )
        assert proc.avg_revenue_per_run == 50.0


class TestTemporalMemory:
    @pytest.fixture
    def mem(self):
        from apps.core.memory.temporal.temporal_memory import TemporalMemory
        return TemporalMemory()

    @pytest.mark.asyncio
    async def test_record_creates_event(self, mem):
        from apps.core.memory.temporal.temporal_memory import EventType
        with patch.object(mem, "_persist", new=AsyncMock()):
            ev = await mem.record(
                EventType.INCOME_CYCLE,
                entity_id="loop_1",
                entity_name="IncomeLoop",
                payload={"revenue": 42.0, "strategy": "content"},
                success=True,
            )
        assert ev.id
        assert ev.event_type == EventType.INCOME_CYCLE
        assert ev.payload["revenue"] == 42.0

    @pytest.mark.asyncio
    async def test_recent_returns_latest_events(self, mem):
        from apps.core.memory.temporal.temporal_memory import EventType
        with patch.object(mem, "_persist", new=AsyncMock()):
            for i in range(5):
                await mem.record(EventType.TOOL_CALL, "t1", "Tool", {"call": i})

        recent = await mem.recent(n=3)
        assert len(recent) == 3
        # Most recent last
        assert recent[-1].payload["call"] == 4

    @pytest.mark.asyncio
    async def test_since_filters_by_time(self, mem):
        from apps.core.memory.temporal.temporal_memory import EventType
        with patch.object(mem, "_persist", new=AsyncMock()):
            # Record an event then query for last 60 seconds
            ev = await mem.record(EventType.SYSTEM, "sys", "System", {"msg": "test"})
            last_minute = await mem.since(minutes=1)

        assert ev in last_minute

    @pytest.mark.asyncio
    async def test_failures_returns_only_failed(self, mem):
        from apps.core.memory.temporal.temporal_memory import EventType
        with patch.object(mem, "_persist", new=AsyncMock()):
            await mem.record(EventType.TOOL_CALL, "t1", "Tool", {}, success=True)
            await mem.record(EventType.TOOL_CALL, "t2", "Tool", {}, success=False)
            await mem.record(EventType.TOOL_CALL, "t3", "Tool", {}, success=False)

        failures = await mem.failures(hours=1)
        assert len(failures) == 2
        assert all(not ev.success for ev in failures)

    @pytest.mark.asyncio
    async def test_causal_chain_backward(self, mem):
        from apps.core.memory.temporal.temporal_memory import EventType
        with patch.object(mem, "_persist", new=AsyncMock()):
            e1 = await mem.record(EventType.SYSTEM, "sys", "System", {})
            e2 = await mem.record(EventType.TOOL_CALL, "t1", "Tool", {}, caused_by=[e1.id])
            e3 = await mem.record(EventType.ERROR, "t1", "Tool", {}, caused_by=[e2.id])

        chain = await mem.causal_chain(e3.id, direction="backward")
        chain_ids = {ev.id for ev in chain}
        assert e3.id in chain_ids
        assert e2.id in chain_ids

    @pytest.mark.asyncio
    async def test_causal_chain_forward(self, mem):
        from apps.core.memory.temporal.temporal_memory import EventType
        with patch.object(mem, "_persist", new=AsyncMock()):
            e1 = await mem.record(EventType.SYSTEM, "sys", "System", {})
            e2 = await mem.record(EventType.TOOL_CALL, "t1", "Tool", {}, caused_by=[e1.id])

        chain = await mem.causal_chain(e1.id, direction="forward")
        chain_ids = {ev.id for ev in chain}
        assert e1.id in chain_ids
        assert e2.id in chain_ids

    @pytest.mark.asyncio
    async def test_event_type_filter_in_since(self, mem):
        from apps.core.memory.temporal.temporal_memory import EventType
        with patch.object(mem, "_persist", new=AsyncMock()):
            await mem.record(EventType.INCOME_CYCLE, "loop", "Loop", {})
            await mem.record(EventType.TOOL_CALL, "tool", "Tool", {})
            income_events = await mem.since(minutes=5, event_type=EventType.INCOME_CYCLE)

        assert len(income_events) == 1
        assert income_events[0].event_type == EventType.INCOME_CYCLE

    @pytest.mark.asyncio
    async def test_summary_counts_events(self, mem):
        from apps.core.memory.temporal.temporal_memory import EventType
        with patch.object(mem, "_persist", new=AsyncMock()):
            await mem.record(EventType.INCOME_CYCLE, "l1", "Loop", {}, success=True)
            await mem.record(EventType.ERROR, "e1", "Error", {}, success=False)

        summary = mem.summary()
        assert summary["total_events"] == 2
        assert summary["failure_count"] == 1

    @pytest.mark.asyncio
    async def test_pattern_frequency_by_hour(self, mem):
        from apps.core.memory.temporal.temporal_memory import EventType
        with patch.object(mem, "_persist", new=AsyncMock()):
            for _ in range(3):
                await mem.record(EventType.INCOME_CYCLE, "l1", "Loop", {})

        freq = await mem.pattern_frequency(EventType.INCOME_CYCLE, window_hours=1)
        assert freq["total_events"] == 3
        assert "by_hour" in freq

    def test_event_serialization_roundtrip(self):
        from apps.core.memory.temporal.temporal_memory import TemporalEvent, EventType
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        ev = TemporalEvent(
            id="test_ev",
            ts=now.timestamp(),
            ts_iso=now.isoformat(),
            event_type=EventType.AI_CALL,
            entity_id="ai_1",
            entity_name="AIClient",
            payload={"model": "llama-3", "tokens": 500},
            caused_by=[], caused=[],
            tags=["llm", "inference"],
            success=True,
            importance=0.8,
        )
        d = ev.to_dict()
        restored = TemporalEvent.from_dict(d)
        assert restored.id == ev.id
        assert restored.event_type == EventType.AI_CALL
        assert restored.payload["tokens"] == 500

    @pytest.mark.asyncio
    async def test_eviction_keeps_under_limit(self, mem):
        from apps.core.memory.temporal.temporal_memory import EventType, MAX_IN_MEMORY
        with patch.object(mem, "_persist", new=AsyncMock()):
            for i in range(MAX_IN_MEMORY + 50):
                await mem.record(EventType.SYSTEM, "sys", "S", {"i": i})

        assert len(mem._events) <= MAX_IN_MEMORY
