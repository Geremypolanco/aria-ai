"""Phase 11 tests — Memory Extensions (EconomicMemoryStore, ClientMemory, WorkflowMemory)."""

from __future__ import annotations
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def _mock_cache():
    c = MagicMock()
    c.get = AsyncMock(return_value=None)
    c.set = AsyncMock(return_value=True)
    return c


def _mock_ai(
    content="1. Focus on highest ROI channels\n2. Repeat what works\n3. Track all experiments",
):
    ai = MagicMock()
    r = MagicMock()
    r.success = True
    r.content = content
    ai.complete = AsyncMock(return_value=r)
    return ai


# ── Economic Memory Store ─────────────────────────────────────────────────────


class TestEconomicMemoryStore:
    @pytest.fixture
    def store(self):
        with patch("apps.memory.economic.economic_memory.get_cache", return_value=_mock_cache()):
            with patch(
                "apps.memory.economic.economic_memory.get_ai_client", return_value=_mock_ai()
            ):
                from apps.memory.economic.economic_memory import EconomicMemoryStore

                return EconomicMemoryStore()

    @pytest.mark.asyncio
    async def test_remember_returns_memory(self, store):
        from apps.memory.economic.economic_memory import EconomicMemory

        mem = await store.remember(
            "profitable_pattern", "Email campaigns yielded 4x ROI", impact_usd=500.0
        )
        assert isinstance(mem, EconomicMemory)
        assert mem.memory_id

    @pytest.mark.asyncio
    async def test_memory_stored_in_list(self, store):
        await store.remember("strategy", "Flash sales worked well", impact_usd=800.0)
        assert len(store._memories) == 1

    @pytest.mark.asyncio
    async def test_remember_with_tags(self, store):
        mem = await store.remember(
            "experiment", "Quiz drove leads", impact_usd=300.0, tags=["quiz", "lead_gen"]
        )
        assert mem.tags == ["quiz", "lead_gen"]

    @pytest.mark.asyncio
    async def test_recall_finds_matching_memory(self, store):
        await store.remember(
            "profitable", "Email marketing drives 5x ROI", impact_usd=1000.0, tags=["email"]
        )
        results = await store.recall("email")
        assert len(results) >= 1

    @pytest.mark.asyncio
    async def test_recall_by_type_filters_correctly(self, store):
        await store.remember("profitable_pattern", "Email works", impact_usd=500.0)
        await store.remember("failed_strategy", "Paid ads had low ROI", impact_usd=-200.0)
        results = await store.recall("email", memory_type="profitable_pattern")
        assert all(r.memory_type == "profitable_pattern" for r in results)

    @pytest.mark.asyncio
    async def test_recall_increments_times_recalled(self, store):
        await store.remember("pattern", "Flash sale works", impact_usd=200.0, tags=["flash_sale"])
        await store.recall("flash_sale")
        assert store._memories[0]["times_recalled"] >= 1

    @pytest.mark.asyncio
    async def test_extract_insights_returns_list(self, store):
        await store.remember("profitable", "Content drives organic traffic", impact_usd=400.0)
        await store.remember("profitable", "Email converts at 3%", impact_usd=300.0)
        insights = await store.extract_insights()
        assert isinstance(insights, list)
        assert len(insights) >= 1

    @pytest.mark.asyncio
    async def test_insights_have_required_keys(self, store):
        await store.remember("pattern", "Test observation", impact_usd=100.0)
        insights = await store.extract_insights()
        for insight in insights:
            assert "insight" in insight
            assert "actionable" in insight

    def test_profitable_patterns_filters_by_impact(self, store):
        store._memories = [
            {"memory_id": "m1", "impact_usd": 500.0, "memory_type": "profitable"},
            {"memory_id": "m2", "impact_usd": 50.0, "memory_type": "neutral"},
        ]
        patterns = store.profitable_patterns(min_impact=100.0)
        assert len(patterns) == 1
        assert patterns[0]["memory_id"] == "m1"

    def test_failed_strategies_filters_negative_impact(self, store):
        store._memories = [
            {"memory_id": "m1", "impact_usd": -200.0, "memory_type": "failed"},
            {"memory_id": "m2", "impact_usd": 300.0, "memory_type": "profitable"},
        ]
        failed = store.failed_strategies(max_impact=-50.0)
        assert len(failed) == 1
        assert failed[0]["memory_id"] == "m1"

    def test_memory_summary_has_required_keys(self, store):
        summary = store.memory_summary()
        assert "total_memories" in summary
        assert "by_type" in summary
        assert "net_impact" in summary

    @pytest.mark.asyncio
    async def test_multiple_memories_accumulate(self, store):
        await store.remember("a", "Memory 1", 100.0)
        await store.remember("b", "Memory 2", 200.0)
        await store.remember("c", "Memory 3", 300.0)
        assert len(store._memories) == 3


# ── Client Memory ─────────────────────────────────────────────────────────────


class TestClientMemory:
    @pytest.fixture
    def memory(self):
        with patch("apps.memory.client.client_memory.get_cache", return_value=_mock_cache()):
            with patch(
                "apps.memory.client.client_memory.get_ai_client", return_value=_mock_ai("positive")
            ):
                from apps.memory.client.client_memory import ClientMemory

                return ClientMemory()

    @pytest.mark.asyncio
    async def test_upsert_profile_returns_profile(self, memory):
        from apps.memory.client.client_memory import ClientProfile

        profile = await memory.upsert_profile("Alice", "alice@example.com", "TechCorp")
        assert isinstance(profile, ClientProfile)
        assert profile.profile_id

    @pytest.mark.asyncio
    async def test_upsert_same_email_updates_profile(self, memory):
        await memory.upsert_profile("Alice", "alice@test.com", "OldCorp")
        await memory.upsert_profile("Alice Updated", "alice@test.com", "NewCorp")
        assert len(memory._profiles) == 1
        assert memory._profiles[0]["company"] == "NewCorp"

    @pytest.mark.asyncio
    async def test_record_interaction_returns_interaction(self, memory):
        from apps.memory.client.client_memory import ClientInteraction

        profile = await memory.upsert_profile("Bob", "bob@test.com")
        interaction = await memory.record_interaction(
            profile.profile_id, "purchase", "Bought Plan A", value_usd=99.0
        )
        assert isinstance(interaction, ClientInteraction)
        assert interaction.interaction_id

    @pytest.mark.asyncio
    async def test_record_interaction_has_sentiment(self, memory):
        profile = await memory.upsert_profile("Carol", "carol@test.com")
        interaction = await memory.record_interaction(
            profile.profile_id, "support", "Great service!", value_usd=0.0
        )
        assert interaction.sentiment in ("positive", "neutral", "negative")

    @pytest.mark.asyncio
    async def test_purchase_updates_total_spent(self, memory):
        profile = await memory.upsert_profile("Dave", "dave@test.com")
        await memory.record_interaction(
            profile.profile_id, "purchase", "Bought item", value_usd=150.0
        )
        updated = next(p for p in memory._profiles if p["profile_id"] == profile.profile_id)
        assert updated["total_spent_usd"] == 150.0

    @pytest.mark.asyncio
    async def test_segment_client_vip_for_high_spenders(self, memory):
        profile = await memory.upsert_profile("Eve", "eve@test.com")
        for _ in range(11):
            await memory.record_interaction(
                profile.profile_id, "purchase", "Purchased", value_usd=100.0
            )
        segment = await memory.segment_client(profile.profile_id)
        assert segment == "vip"

    @pytest.mark.asyncio
    async def test_segment_client_standard_for_new(self, memory):
        profile = await memory.upsert_profile("Frank", "frank@test.com")
        segment = await memory.segment_client(profile.profile_id)
        assert segment == "standard"

    @pytest.mark.asyncio
    async def test_personalize_offer_returns_dict(self, memory):
        profile = await memory.upsert_profile("Grace", "grace@test.com")
        offer = await memory.personalize_offer(profile.profile_id, ["premium_plan", "basic_plan"])
        assert "recommended_product" in offer
        assert "offer" in offer

    def test_get_profile_by_email(self, memory):
        import asyncio

        asyncio.run(memory.upsert_profile("Hank", "hank@test.com", "Corp"))
        result = memory.get_profile("hank@test.com")
        assert result is not None
        assert result["name"] == "Hank"

    def test_vip_clients_returns_vip_only(self, memory):
        memory._profiles = [
            {"profile_id": "p1", "segment": "vip"},
            {"profile_id": "p2", "segment": "standard"},
            {"profile_id": "p3", "segment": "vip"},
        ]
        vips = memory.vip_clients()
        assert len(vips) == 2
        assert all(p["segment"] == "vip" for p in vips)

    def test_at_risk_clients_includes_churned(self, memory):
        memory._profiles = [
            {"profile_id": "p1", "segment": "at_risk"},
            {"profile_id": "p2", "segment": "churned"},
            {"profile_id": "p3", "segment": "vip"},
        ]
        at_risk = memory.at_risk_clients()
        assert len(at_risk) == 2

    def test_client_memory_summary_has_required_keys(self, memory):
        summary = memory.client_memory_summary()
        assert "total_profiles" in summary
        assert "total_interactions" in summary
        assert "by_segment" in summary
        assert "vip_count" in summary


# ── Workflow Memory ───────────────────────────────────────────────────────────


class TestWorkflowMemory:
    @pytest.fixture
    def memory(self):
        with patch("apps.memory.workflow.workflow_memory.get_cache", return_value=_mock_cache()):
            with patch(
                "apps.memory.workflow.workflow_memory.get_ai_client", return_value=_mock_ai()
            ):
                from apps.memory.workflow.workflow_memory import WorkflowMemory

                return WorkflowMemory()

    @pytest.mark.asyncio
    async def test_record_returns_workflow_record(self, memory):
        from apps.memory.workflow.workflow_memory import WorkflowRecord

        rec = await memory.record(
            "generate_content",
            "content",
            inputs={"topic": "AI", "length": 800},
            outputs={"word_count": 850, "seo_score": 0.9},
            success=True,
            success_score=0.95,
        )
        assert isinstance(rec, WorkflowRecord)
        assert rec.record_id

    @pytest.mark.asyncio
    async def test_record_stores_in_memory(self, memory):
        await memory.record("send_email", "email", {}, {}, success=True, success_score=0.8)
        assert len(memory._records) == 1

    @pytest.mark.asyncio
    async def test_record_has_lessons(self, memory):
        rec = await memory.record("run_ad", "ads", {}, {}, success=True, success_score=0.7)
        assert isinstance(rec.lessons, list)
        assert len(rec.lessons) >= 1

    @pytest.mark.asyncio
    async def test_failed_workflow_has_lessons(self, memory):
        rec = await memory.record(
            "deploy_quiz", "quiz", {}, {}, success=False, success_score=0.0, error="API timeout"
        )
        assert isinstance(rec.lessons, list)
        assert len(rec.lessons) >= 1

    @pytest.mark.asyncio
    async def test_recall_similar_returns_matching(self, memory):
        await memory.record("generate_content", "content", {}, {}, success=True, success_score=0.9)
        await memory.record("send_email", "email", {}, {}, success=True, success_score=0.8)
        results = await memory.recall_similar("generate")
        assert len(results) >= 1
        assert all("generate" in r.workflow_name for r in results)

    @pytest.mark.asyncio
    async def test_recall_similar_by_type(self, memory):
        await memory.record("write_blog", "content", {}, {}, success=True, success_score=0.85)
        await memory.record("write_script", "content", {}, {}, success=True, success_score=0.9)
        await memory.record("run_ad", "ads", {}, {}, success=True, success_score=0.7)
        results = await memory.recall_similar("write", workflow_type="content")
        assert all(r.workflow_type == "content" for r in results)

    @pytest.mark.asyncio
    async def test_get_best_practices_returns_list(self, memory):
        await memory.record("content_gen", "content", {}, {}, success=True, success_score=0.9)
        practices = await memory.get_best_practices("content")
        assert isinstance(practices, list)
        assert len(practices) >= 1

    @pytest.mark.asyncio
    async def test_get_best_practices_empty_for_unknown_type(self, memory):
        practices = await memory.get_best_practices("unknown_type_xyz")
        assert isinstance(practices, list)

    def test_success_rate_returns_float(self, memory):
        memory._records = [
            {"workflow_type": "content", "success": True},
            {"workflow_type": "content", "success": False},
            {"workflow_type": "content", "success": True},
        ]
        rate = memory.success_rate("content")
        assert abs(rate - 0.67) < 0.01

    def test_success_rate_zero_when_no_records(self, memory):
        rate = memory.success_rate("nonexistent")
        assert rate == 0.0

    def test_failed_workflows_returns_failures(self, memory):
        memory._records = [
            {"workflow_type": "email", "success": False, "error": "Timeout"},
            {"workflow_type": "email", "success": True},
            {"workflow_type": "content", "success": False, "error": "API error"},
        ]
        failed = memory.failed_workflows("email")
        assert len(failed) == 1

    def test_workflow_analytics_has_required_keys(self, memory):
        analytics = memory.workflow_analytics()
        assert "total_records" in analytics
        assert "success_rate_pct" in analytics
        assert "by_type" in analytics
        assert "avg_duration_seconds" in analytics

    @pytest.mark.asyncio
    async def test_analytics_reflects_records(self, memory):
        await memory.record(
            "task_a", "content", {}, {}, success=True, success_score=0.9, duration_seconds=5.0
        )
        await memory.record(
            "task_b", "email", {}, {}, success=False, success_score=0.0, duration_seconds=3.0
        )
        analytics = memory.workflow_analytics()
        assert analytics["total_records"] == 2
        assert analytics["success_rate_pct"] == 50.0
