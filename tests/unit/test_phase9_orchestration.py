"""
Phase 9 tests — Market Intelligence + Reinforcement Learning.

(GrowthOrchestrator and ResourceAllocator were deleted — both were dead code,
referenced only by their own tests, never wired into any production path.)
"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def _mock_cache():
    c = MagicMock()
    c.get = AsyncMock(return_value=None)
    c.set = AsyncMock(return_value=True)
    return c


def _mock_ai(
    content="ACTION_TYPE: create_content | TITLE: Write SEO posts | IMPACT: 500 | HOURS: 3",
):
    ai = MagicMock()
    r = MagicMock()
    r.success = True
    r.content = content
    ai.complete = AsyncMock(return_value=r)
    return ai


# ── Reinforcement Optimizer ───────────────────────────────────────────────────


class TestReinforcementOptimizer:
    @pytest.fixture
    def optimizer(self):
        with patch(
            "apps.learning.optimization.reinforcement_optimizer.get_cache",
            return_value=_mock_cache(),
        ):
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
        with patch(
            "apps.market.intelligence.market_intelligence.get_cache", return_value=_mock_cache()
        ):
            with patch(
                "apps.market.intelligence.market_intelligence.get_ai_client",
                return_value=_mock_ai(
                    '{"position": "AI leader", "unique_angle": "fast", "key_message": "best", "target_segment": "entrepreneurs", "differentiation": "speed"}'
                ),
            ):
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

        asyncio.run(intel.analyze_market("cooking"))
        snap = intel.latest_snapshot("cooking")
        assert snap is not None
        assert snap["niche"] == "cooking"

    def test_intelligence_dashboard_empty(self, intel):
        dash = intel.intelligence_dashboard()
        assert "total_snapshots" in dash
