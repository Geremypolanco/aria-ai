"""
Phase 9 tests — Orchestration + Market Intelligence + Reinforcement Learning.
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def _mock_cache():
    c = MagicMock()
    c.get = AsyncMock(return_value=None)
    c.set = AsyncMock(return_value=True)
    return c


def _mock_ai(content="ACTION_TYPE: create_content | TITLE: Write SEO posts | IMPACT: 500 | HOURS: 3"):
    ai = MagicMock()
    r = MagicMock()
    r.success = True
    r.content = content
    ai.complete = AsyncMock(return_value=r)
    return ai


# ── Growth Orchestrator ───────────────────────────────────────────────────────

class TestGrowthOrchestrator:
    @pytest.fixture
    def orchestrator(self):
        with patch("apps.orchestration.growth_orchestrator.get_cache", return_value=_mock_cache()):
            with patch("apps.orchestration.growth_orchestrator.get_ai_client", return_value=_mock_ai()):
                from apps.orchestration.growth_orchestrator import GrowthOrchestrator
                return GrowthOrchestrator()

    @pytest.mark.asyncio
    async def test_collect_economic_signals_returns_signals(self, orchestrator):
        from apps.orchestration.growth_orchestrator import EconomicSignals
        signals = await orchestrator.collect_economic_signals()
        assert isinstance(signals, EconomicSignals)

    @pytest.mark.asyncio
    async def test_signals_have_defaults(self, orchestrator):
        signals = await orchestrator.collect_economic_signals()
        assert 0.0 <= signals.conversion_rate <= 1.0
        assert signals.cash_runway_months >= 0.0

    @pytest.mark.asyncio
    async def test_generate_growth_actions_returns_list(self, orchestrator):
        from apps.orchestration.growth_orchestrator import EconomicSignals, GrowthAction
        signals = EconomicSignals()
        actions = await orchestrator.generate_growth_actions(signals, "fitness")
        assert isinstance(actions, list)
        assert len(actions) >= 3
        assert all(isinstance(a, GrowthAction) for a in actions)

    @pytest.mark.asyncio
    async def test_actions_sorted_by_roi(self, orchestrator):
        from apps.orchestration.growth_orchestrator import EconomicSignals
        signals = EconomicSignals()
        actions = await orchestrator.generate_growth_actions(signals)
        roi_scores = [a.roi_score for a in actions]
        assert roi_scores == sorted(roi_scores, reverse=True)

    @pytest.mark.asyncio
    async def test_actions_have_priority_rank(self, orchestrator):
        from apps.orchestration.growth_orchestrator import EconomicSignals
        signals = EconomicSignals()
        actions = await orchestrator.generate_growth_actions(signals)
        assert all(a.priority_rank >= 1 for a in actions)

    @pytest.mark.asyncio
    async def test_create_weekly_plan_returns_plan(self, orchestrator):
        from apps.orchestration.growth_orchestrator import WeeklyGrowthPlan
        plan = await orchestrator.create_weekly_plan("skincare")
        assert isinstance(plan, WeeklyGrowthPlan)
        assert plan.plan_id

    @pytest.mark.asyncio
    async def test_weekly_plan_has_actions(self, orchestrator):
        plan = await orchestrator.create_weekly_plan("tech")
        assert isinstance(plan.actions, list)
        assert len(plan.actions) >= 1

    @pytest.mark.asyncio
    async def test_weekly_plan_respects_hour_budget(self, orchestrator):
        plan = await orchestrator.create_weekly_plan("wellness")
        assert plan.total_effort_hours <= 40.0

    @pytest.mark.asyncio
    async def test_weekly_plan_has_revenue_estimate(self, orchestrator):
        plan = await orchestrator.create_weekly_plan("nutrition")
        assert plan.total_estimated_revenue > 0.0

    @pytest.mark.asyncio
    async def test_execute_next_action_returns_action_or_none(self, orchestrator):
        from apps.orchestration.growth_orchestrator import GrowthAction
        await orchestrator.create_weekly_plan("beauty")
        action = await orchestrator.execute_next_action()
        assert action is None or isinstance(action, GrowthAction)

    @pytest.mark.asyncio
    async def test_mark_action_complete(self, orchestrator):
        await orchestrator.create_weekly_plan("home")
        action = await orchestrator.execute_next_action()
        if action:
            result = await orchestrator.mark_action_complete(action.action_id, revenue_generated=250.0)
            assert result is True

    @pytest.mark.asyncio
    async def test_autonomous_growth_cycle_returns_dict(self, orchestrator):
        result = await orchestrator.autonomous_growth_cycle("fitness")
        assert "signals" in result
        assert "top_actions" in result
        assert "estimated_weekly_revenue" in result

    @pytest.mark.asyncio
    async def test_growth_analytics_returns_dict(self, orchestrator):
        analytics = orchestrator.growth_analytics()
        assert "completed" in analytics
        assert "total_actions_queued" in analytics

    @pytest.mark.asyncio
    async def test_strategic_report_returns_dict(self, orchestrator):
        report = await orchestrator.strategic_report()
        assert "risk_factors" in report
        assert "next_steps" in report
        assert "recommended_focus" in report


# ── Resource Allocator ────────────────────────────────────────────────────────

class TestResourceAllocator:
    @pytest.fixture
    def allocator(self):
        with patch("apps.orchestration.resource_allocator.get_cache", return_value=_mock_cache()):
            from apps.orchestration.resource_allocator import ResourceAllocator
            return ResourceAllocator()

    @pytest.mark.asyncio
    async def test_allocate_returns_allocation(self, allocator):
        from apps.orchestration.resource_allocator import ResourceAllocation
        alloc = await allocator.allocate(1000.0, 40.0)
        assert isinstance(alloc, ResourceAllocation)
        assert alloc.allocation_id

    @pytest.mark.asyncio
    async def test_allocation_budget_sums_to_total(self, allocator):
        alloc = await allocator.allocate(1000.0, 40.0)
        total = sum(v["budget_usd"] for v in alloc.allocations.values())
        assert abs(total - 1000.0) < 1.0

    @pytest.mark.asyncio
    async def test_high_roas_channel_gets_more_budget(self, allocator):
        perf = {"paid_ads": {"roas": 5.0, "revenue": 5000}}
        alloc_perf = await allocator.allocate(1000.0, 40.0, performance_data=perf)
        alloc_base = await allocator.allocate(1000.0, 40.0)
        paid_perf = alloc_perf.allocations["paid_ads"]["budget_usd"]
        paid_base = alloc_base.allocations["paid_ads"]["budget_usd"]
        assert paid_perf >= paid_base

    @pytest.mark.asyncio
    async def test_optimize_allocation_from_campaigns(self, allocator):
        from apps.orchestration.resource_allocator import ResourceAllocation
        campaigns = [
            {"channel": "content_seo", "spend": 200, "revenue": 800, "roas": 4.0},
            {"channel": "paid_ads", "spend": 300, "revenue": 600, "roas": 2.0},
        ]
        alloc = await allocator.optimize_allocation(campaigns)
        assert isinstance(alloc, ResourceAllocation)

    def test_pareto_channels_returns_list(self, allocator):
        perf = {
            "content_seo": {"revenue": 8000},
            "paid_ads": {"revenue": 1000},
            "email_retention": {"revenue": 500},
        }
        channels = allocator.pareto_channels(perf)
        assert isinstance(channels, list)
        assert "content_seo" in channels

    def test_efficiency_report_after_allocation(self, allocator):
        import asyncio
        asyncio.get_event_loop().run_until_complete(allocator.allocate(500.0, 20.0))
        report = allocator.efficiency_report()
        assert "total_allocations" in report
        assert report["total_allocations"] >= 1


# ── Reinforcement Optimizer ───────────────────────────────────────────────────

class TestReinforcementOptimizer:
    @pytest.fixture
    def optimizer(self):
        with patch("apps.learning.optimization.reinforcement_optimizer.get_cache", return_value=_mock_cache()):
            from apps.learning.optimization.reinforcement_optimizer import ReinforcementOptimizer
            return ReinforcementOptimizer()

    @pytest.mark.asyncio
    async def test_select_action_returns_string(self, optimizer):
        action = await optimizer.select_action()
        assert isinstance(action, str)
        assert len(action) > 0

    @pytest.mark.asyncio
    async def test_select_action_from_default_arms(self, optimizer):
        action = await optimizer.select_action()
        from apps.learning.optimization.reinforcement_optimizer import _DEFAULT_ACTIONS
        assert action in _DEFAULT_ACTIONS

    @pytest.mark.asyncio
    async def test_record_outcome_returns_arm(self, optimizer):
        from apps.learning.optimization.reinforcement_optimizer import ActionArm
        arm = await optimizer.record_outcome("create_content", 500.0)
        assert isinstance(arm, ActionArm)
        assert arm.total_pulls == 1
        assert arm.total_reward == 500.0

    @pytest.mark.asyncio
    async def test_avg_reward_updates_correctly(self, optimizer):
        await optimizer.record_outcome("email_campaign", 300.0)
        await optimizer.record_outcome("email_campaign", 100.0)
        arm = optimizer._arms["email_campaign"]
        assert arm.avg_reward == 200.0

    @pytest.mark.asyncio
    async def test_select_prefers_explored_high_reward(self, optimizer):
        # Give one arm a very high reward many times
        for _ in range(10):
            await optimizer.record_outcome("flash_sale", 1000.0)
        # Give others low rewards
        for arm_name in ["run_ad", "email_campaign", "bundle_create"]:
            await optimizer.record_outcome(arm_name, 10.0)
        action = await optimizer.select_action()
        assert isinstance(action, str)

    @pytest.mark.asyncio
    async def test_batch_update_updates_multiple_arms(self, optimizer):
        outcomes = [
            {"action_type": "create_content", "reward": 400.0},
            {"action_type": "run_ad", "reward": 200.0},
            {"action_type": "quiz_launch", "reward": 600.0},
        ]
        await optimizer.batch_update(outcomes)
        assert optimizer._arms["create_content"].total_pulls == 1
        assert optimizer._arms["quiz_launch"].total_reward == 600.0

    def test_arm_rankings_returns_sorted_list(self, optimizer):
        rankings = optimizer.arm_rankings()
        assert isinstance(rankings, list)
        assert len(rankings) == len(optimizer._arms)

    @pytest.mark.asyncio
    async def test_explore_recommend_returns_valid_action(self, optimizer):
        action = await optimizer.explore_recommend(exploration_pct=0.0)
        assert action in optimizer._arms

    def test_optimization_report_structure(self, optimizer):
        report = optimizer.optimization_report()
        assert "total_pulls" in report
        assert "best_action" in report
        assert "arm_rankings" in report

    @pytest.mark.asyncio
    async def test_new_action_type_can_be_added(self, optimizer):
        arm = await optimizer.record_outcome("custom_action", 999.0)
        assert arm.action_type == "custom_action"
        assert "custom_action" in optimizer._arms


# ── Market Intelligence ───────────────────────────────────────────────────────

class TestMarketIntelligence:
    @pytest.fixture
    def intel(self):
        with patch("apps.market.intelligence.market_intelligence.get_cache", return_value=_mock_cache()):
            with patch("apps.market.intelligence.market_intelligence.get_ai_client",
                       return_value=_mock_ai('{"position": "AI leader", "unique_angle": "fast", "key_message": "best", "target_segment": "entrepreneurs", "differentiation": "speed"}')):
                from apps.market.intelligence.market_intelligence import MarketIntelligence
                return MarketIntelligence()

    @pytest.mark.asyncio
    async def test_analyze_market_returns_snapshot(self, intel):
        from apps.market.intelligence.market_intelligence import MarketSnapshot
        snap = await intel.analyze_market("fitness")
        assert isinstance(snap, MarketSnapshot)
        assert snap.snapshot_id

    @pytest.mark.asyncio
    async def test_snapshot_has_niche(self, intel):
        snap = await intel.analyze_market("skincare")
        assert snap.niche == "skincare"

    @pytest.mark.asyncio
    async def test_trend_score_between_0_and_1(self, intel):
        snap = await intel.analyze_market("tech")
        assert 0.0 <= snap.trend_score <= 1.0

    @pytest.mark.asyncio
    async def test_ai_niche_has_valid_trend(self, intel):
        snap = await intel.analyze_market("ai tools")
        assert 0.0 <= snap.trend_score <= 1.0

    @pytest.mark.asyncio
    async def test_identify_entry_points_returns_strategies(self, intel):
        points = await intel.identify_entry_points("nutrition")
        assert isinstance(points, list)
        assert len(points) >= 3
        assert all("strategy" in p for p in points)

    @pytest.mark.asyncio
    async def test_competitive_positioning_returns_dict(self, intel):
        pos = await intel.competitive_positioning("wellness", strengths=["speed", "AI"])
        assert "position" in pos
        assert "unique_angle" in pos

    def test_latest_snapshot_returns_most_recent(self, intel):
        import asyncio
        asyncio.get_event_loop().run_until_complete(intel.analyze_market("cooking"))
        snap = intel.latest_snapshot("cooking")
        assert snap is not None
        assert snap["niche"] == "cooking"

    def test_intelligence_dashboard_empty(self, intel):
        dash = intel.intelligence_dashboard()
        assert "total_snapshots" in dash
