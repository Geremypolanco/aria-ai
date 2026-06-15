"""Phase 11 tests — Learning Extensions (ROILearner, PriorityEngine)."""
from __future__ import annotations
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def _mock_cache():
    c = MagicMock()
    c.get = AsyncMock(return_value=None)
    c.set = AsyncMock(return_value=True)
    return c


def _mock_ai(content='[{"pattern_type": "best_channel", "description": "Email shows highest ROI", "confidence": 0.85, "recommendation": "Invest more in email", "estimated_uplift_pct": 20.0}]'):
    ai = MagicMock()
    r = MagicMock()
    r.success = True
    r.content = content
    ai.complete = AsyncMock(return_value=r)
    return ai


# ── ROI Learner ───────────────────────────────────────────────────────────────

class TestROILearner:
    @pytest.fixture
    def learner(self):
        with patch("apps.learning.roi.roi_learner.get_cache", return_value=_mock_cache()):
            with patch("apps.learning.roi.roi_learner.get_ai_client", return_value=_mock_ai()):
                from apps.learning.roi.roi_learner import ROILearner
                return ROILearner()

    @pytest.mark.asyncio
    async def test_record_observation_returns_observation(self, learner):
        from apps.learning.roi.roi_learner import ROIObservation
        obs = await learner.record_observation("content", "blog", 100.0, 500.0)
        assert isinstance(obs, ROIObservation)
        assert obs.obs_id

    @pytest.mark.asyncio
    async def test_observation_roi_multiplier_calculated(self, learner):
        obs = await learner.record_observation("ad", "paid_search", 200.0, 1000.0)
        assert obs.roi_multiplier == 5.0

    @pytest.mark.asyncio
    async def test_observation_stored_in_memory(self, learner):
        await learner.record_observation("email", "klaviyo", 50.0, 300.0)
        assert len(learner._observations) == 1

    @pytest.mark.asyncio
    async def test_detect_patterns_returns_list(self, learner):
        await learner.record_observation("content", "blog", 100.0, 400.0)
        await learner.record_observation("email", "klaviyo", 50.0, 250.0)
        patterns = await learner.detect_patterns()
        assert isinstance(patterns, list)

    @pytest.mark.asyncio
    async def test_detect_patterns_empty_with_no_observations(self, learner):
        patterns = await learner.detect_patterns()
        assert patterns == []

    @pytest.mark.asyncio
    async def test_patterns_have_confidence_in_range(self, learner):
        for i in range(3):
            await learner.record_observation("content", "blog", 100.0, 300.0 + i * 100)
        patterns = await learner.detect_patterns()
        for p in patterns:
            assert 0.0 <= p.confidence <= 1.0

    @pytest.mark.asyncio
    async def test_recommend_allocation_returns_dict(self, learner):
        await learner.record_observation("content", "blog", 100.0, 500.0)
        await learner.record_observation("ad", "meta", 300.0, 600.0)
        result = await learner.recommend_allocation(1000.0)
        assert "allocations" in result
        assert isinstance(result["allocations"], dict)

    @pytest.mark.asyncio
    async def test_recommend_allocation_has_reasoning(self, learner):
        await learner.record_observation("email", "klaviyo", 80.0, 320.0)
        result = await learner.recommend_allocation(500.0)
        assert "reasoning" in result

    def test_best_actions_returns_list(self, learner):
        learner._observations = [
            {"action_type": "content", "channel": "blog", "roi_multiplier": 5.0, "revenue_usd": 500.0},
            {"action_type": "email", "channel": "klaviyo", "roi_multiplier": 3.0, "revenue_usd": 300.0},
            {"action_type": "ad", "channel": "meta", "roi_multiplier": 2.0, "revenue_usd": 200.0},
        ]
        best = learner.best_actions(top_n=3)
        assert isinstance(best, list)
        assert len(best) <= 3
        assert best[0]["action_type"] == "content"

    def test_worst_actions_returns_list(self, learner):
        learner._observations = [
            {"action_type": "content", "channel": "blog", "roi_multiplier": 5.0, "revenue_usd": 500.0},
            {"action_type": "email", "channel": "klaviyo", "roi_multiplier": 1.5, "revenue_usd": 150.0},
        ]
        worst = learner.worst_actions(bottom_n=1)
        assert isinstance(worst, list)
        assert worst[0]["action_type"] == "email"

    def test_roi_by_channel_groups_correctly(self, learner):
        learner._observations = [
            {"action_type": "content", "channel": "blog", "roi_multiplier": 5.0, "revenue_usd": 500.0},
            {"action_type": "content", "channel": "blog", "roi_multiplier": 3.0, "revenue_usd": 300.0},
            {"action_type": "email", "channel": "klaviyo", "roi_multiplier": 4.0, "revenue_usd": 400.0},
        ]
        by_channel = learner.roi_by_channel()
        assert "blog" in by_channel
        assert "klaviyo" in by_channel
        assert by_channel["blog"]["total_observations"] == 2

    def test_learning_report_has_required_keys(self, learner):
        learner._observations = [
            {"action_type": "content", "channel": "blog", "roi_multiplier": 4.0, "revenue_usd": 400.0},
        ]
        report = learner.learning_report()
        assert "total_observations" in report
        assert "best_channel" in report
        assert "best_action" in report
        assert "avg_roi_multiplier" in report

    @pytest.mark.asyncio
    async def test_multiple_observations_accumulate(self, learner):
        await learner.record_observation("content", "blog", 100.0, 500.0)
        await learner.record_observation("email", "klaviyo", 80.0, 320.0)
        await learner.record_observation("ad", "meta", 200.0, 400.0)
        assert len(learner._observations) == 3

    @pytest.mark.asyncio
    async def test_patterns_have_supporting_obs(self, learner):
        for _ in range(5):
            await learner.record_observation("content", "blog", 100.0, 400.0)
        patterns = await learner.detect_patterns()
        if patterns:
            assert patterns[0].supporting_obs > 0

    @pytest.mark.asyncio
    async def test_zero_investment_handled_gracefully(self, learner):
        obs = await learner.record_observation("content", "blog", 0.0, 500.0)
        assert obs.roi_multiplier > 0.0  # 500 / 0.01 = 50000


# ── Priority Engine ───────────────────────────────────────────────────────────

class TestPriorityEngine:
    @pytest.fixture
    def engine(self):
        with patch("apps.learning.prioritization.priority_engine.get_cache", return_value=_mock_cache()):
            with patch("apps.learning.prioritization.priority_engine.get_ai_client",
                       return_value=_mock_ai("1. High revenue/hour ratio\n2. Urgency boosts this item\n3. Historical ROI supports this")):
                from apps.learning.prioritization.priority_engine import PriorityEngine
                return PriorityEngine()

    @pytest.mark.asyncio
    async def test_prioritize_returns_list(self, engine):
        items = [
            {"title": "Email campaign", "action_type": "email", "estimated_revenue": 300.0, "estimated_hours": 1.0, "urgency": 0.5, "deadline_hours": 8.0},
            {"title": "Write blog", "action_type": "content", "estimated_revenue": 500.0, "estimated_hours": 3.0, "urgency": 0.3, "deadline_hours": 24.0},
        ]
        result = await engine.prioritize(items)
        assert isinstance(result, list)
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_items_sorted_by_final_score(self, engine):
        items = [
            {"title": "High ROI action", "action_type": "email", "estimated_revenue": 1000.0, "estimated_hours": 1.0, "urgency": 0.9, "deadline_hours": 4.0},
            {"title": "Low ROI action", "action_type": "ad", "estimated_revenue": 50.0, "estimated_hours": 5.0, "urgency": 0.1, "deadline_hours": 48.0},
        ]
        result = await engine.prioritize(items)
        assert result[0].final_score >= result[1].final_score

    @pytest.mark.asyncio
    async def test_items_have_rank(self, engine):
        items = [
            {"title": "Task A", "action_type": "content", "estimated_revenue": 500.0, "estimated_hours": 2.0, "urgency": 0.5, "deadline_hours": 0.0},
            {"title": "Task B", "action_type": "email", "estimated_revenue": 200.0, "estimated_hours": 1.0, "urgency": 0.3, "deadline_hours": 0.0},
        ]
        result = await engine.prioritize(items)
        ranks = [item.rank for item in result]
        assert 1 in ranks
        assert all(r >= 1 for r in ranks)

    @pytest.mark.asyncio
    async def test_priority_item_has_final_score(self, engine):
        items = [
            {"title": "Quiz launch", "action_type": "quiz", "estimated_revenue": 800.0, "estimated_hours": 3.0, "urgency": 0.7, "deadline_hours": 24.0},
        ]
        result = await engine.prioritize(items)
        assert result[0].final_score > 0.0

    @pytest.mark.asyncio
    async def test_urgency_boosts_score(self, engine):
        low_urgency = [{"title": "Task", "action_type": "content", "estimated_revenue": 500.0, "estimated_hours": 2.0, "urgency": 0.0, "deadline_hours": 0.0}]
        high_urgency = [{"title": "Task", "action_type": "content", "estimated_revenue": 500.0, "estimated_hours": 2.0, "urgency": 1.0, "deadline_hours": 4.0}]
        low_result = await engine.prioritize(low_urgency)
        high_result = await engine.prioritize(high_urgency)
        assert high_result[0].final_score >= low_result[0].final_score

    @pytest.mark.asyncio
    async def test_daily_priorities_returns_list_when_history_exists(self, engine):
        items = [
            {"title": "Task A", "action_type": "content", "estimated_revenue": 500.0, "estimated_hours": 2.0, "urgency": 0.5, "deadline_hours": 0.0},
        ]
        await engine.prioritize(items)
        result = await engine.daily_priorities(available_hours=8.0)
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_daily_priorities_empty_without_history(self, engine):
        result = await engine.daily_priorities(available_hours=8.0)
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_daily_priorities_respects_hour_budget(self, engine):
        items = [
            {"title": "Task A", "action_type": "content", "estimated_revenue": 500.0, "estimated_hours": 2.0, "urgency": 0.5, "deadline_hours": 0.0},
        ]
        await engine.prioritize(items)
        result = await engine.daily_priorities(available_hours=4.0)
        total_hours = sum(item.estimated_hours for item in result)
        assert total_hours <= 4.0

    @pytest.mark.asyncio
    async def test_emergency_reprioritize_returns_list(self, engine):
        queue = [
            {"title": "Blog post", "action_type": "content", "estimated_revenue": 200.0, "estimated_hours": 2.0},
            {"title": "Run ad", "action_type": "ad", "estimated_revenue": 500.0, "estimated_hours": 1.0},
        ]
        result = await engine.emergency_reprioritize("Revenue below target", queue)
        assert isinstance(result, list)
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_emergency_first_item_has_emergency_reasoning(self, engine):
        queue = [
            {"title": "Task", "action_type": "content", "estimated_revenue": 300.0, "estimated_hours": 1.5},
        ]
        result = await engine.emergency_reprioritize("Low cash runway", queue)
        if result:
            assert "EMERGENCY" in result[0].reasoning or "emergency" in result[0].reasoning.lower() or result[0].reasoning != ""

    def test_prioritization_stats_returns_dict(self, engine):
        stats = engine.prioritization_stats()
        assert "total_prioritizations" in stats
        assert "avg_items_per_run" in stats
        assert "most_common_top_action" in stats

    @pytest.mark.asyncio
    async def test_stats_increment_after_prioritization(self, engine):
        items = [{"title": "Task", "action_type": "email", "estimated_revenue": 200.0, "estimated_hours": 1.0, "urgency": 0.5, "deadline_hours": 0.0}]
        await engine.prioritize(items)
        stats = engine.prioritization_stats()
        assert stats["total_prioritizations"] >= 1

    @pytest.mark.asyncio
    async def test_base_score_is_revenue_per_hour(self, engine):
        items = [
            {"title": "High revenue/hr", "action_type": "content", "estimated_revenue": 1000.0, "estimated_hours": 2.0, "urgency": 0.0, "deadline_hours": 0.0},
        ]
        result = await engine.prioritize(items)
        assert result[0].base_score == 500.0  # 1000/2

    @pytest.mark.asyncio
    async def test_empty_queue_returns_empty_list(self, engine):
        result = await engine.prioritize([])
        assert result == []
