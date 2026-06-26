"""
Phase 10 tests — Economic Intelligence Layer.

Covers:
  - EconomicIntelligence: record_event, record_revenue, record_cost,
    record_conversion, snapshot, prioritize_by_roi, revenue_by_source,
    cost_breakdown, profitability_report, economic_dashboard, recent_events
  - ROITracker: track, update_returns, conclude, top_roi_records,
    failed_investments, roi_summary, ai_roi_recommendation
"""
from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ── Shared mock helpers ────────────────────────────────────────────────────────

def _mock_cache():
    """In-memory cache mock — get returns None, set returns True."""
    c = MagicMock()
    c.get = AsyncMock(return_value=None)
    c.set = AsyncMock(return_value=True)
    return c


def _mock_ai(content: str = "ROI analysis: Double down on content marketing. Best ROI: 320%"):
    """Sync AI client mock whose .complete() is async."""
    ai = MagicMock()
    r = MagicMock()
    r.success = True
    r.content = content
    ai.complete = AsyncMock(return_value=r)
    return ai


def _mock_ai_failed():
    """AI client mock that always returns a failed response."""
    ai = MagicMock()
    r = MagicMock()
    r.success = False
    r.content = ""
    ai.complete = AsyncMock(return_value=r)
    return ai


# ══════════════════════════════════════════════════════════════════════════════
# 1. EconomicIntelligence
# ══════════════════════════════════════════════════════════════════════════════

class TestEconomicIntelligence:
    """15+ tests for EconomicIntelligence."""

    @pytest.fixture(autouse=True)
    def _reset_singleton(self):
        import apps.economics.economic_intelligence as m
        m._instance = None
        yield
        m._instance = None

    @pytest.mark.asyncio
    async def test_record_event_returns_economic_event(self):
        """record_event returns an EconomicEvent with valid fields."""
        from apps.economics.economic_intelligence import EconomicIntelligence, EconomicEvent

        cache = _mock_cache()
        with patch("apps.economics.economic_intelligence.get_cache", return_value=cache):
            ei = EconomicIntelligence()
            event = await ei.record_event(
                event_type="revenue",
                source="shopify",
                amount_usd=500.0,
                metric="revenue",
                value=500.0,
            )

        assert isinstance(event, EconomicEvent)
        assert event.event_id is not None
        assert len(event.event_id) > 0
        assert event.event_type == "revenue"
        assert event.source == "shopify"
        assert event.amount_usd == 500.0

    @pytest.mark.asyncio
    async def test_record_event_persists_to_internal_list(self):
        """record_event appends to internal _events list."""
        from apps.economics.economic_intelligence import EconomicIntelligence

        cache = _mock_cache()
        with patch("apps.economics.economic_intelligence.get_cache", return_value=cache):
            ei = EconomicIntelligence()
            await ei.record_event("revenue", "ads", 100.0)
            await ei.record_event("cost", "hosting", 20.0)

        assert len(ei._events) == 2

    @pytest.mark.asyncio
    async def test_record_revenue_creates_revenue_event(self):
        """record_revenue creates event with type 'revenue'."""
        from apps.economics.economic_intelligence import EconomicIntelligence, EconomicEvent

        cache = _mock_cache()
        with patch("apps.economics.economic_intelligence.get_cache", return_value=cache):
            ei = EconomicIntelligence()
            event = await ei.record_revenue("fiverr", 250.0)

        assert isinstance(event, EconomicEvent)
        assert event.event_type == "revenue"
        assert event.amount_usd == 250.0
        assert event.source == "fiverr"

    @pytest.mark.asyncio
    async def test_record_cost_creates_cost_event(self):
        """record_cost creates event with type 'cost'."""
        from apps.economics.economic_intelligence import EconomicIntelligence, EconomicEvent

        cache = _mock_cache()
        with patch("apps.economics.economic_intelligence.get_cache", return_value=cache):
            ei = EconomicIntelligence()
            event = await ei.record_cost("aws", 50.0, cost_type="infrastructure")

        assert isinstance(event, EconomicEvent)
        assert event.event_type == "cost"
        assert event.amount_usd == 50.0
        assert event.context.get("cost_type") == "infrastructure"

    @pytest.mark.asyncio
    async def test_record_conversion_calculates_roas(self):
        """record_conversion calculates ROAS inline."""
        from apps.economics.economic_intelligence import EconomicIntelligence, EconomicEvent

        cache = _mock_cache()
        with patch("apps.economics.economic_intelligence.get_cache", return_value=cache):
            ei = EconomicIntelligence()
            event = await ei.record_conversion("google_ads", revenue=400.0, cost=100.0)

        assert isinstance(event, EconomicEvent)
        assert event.event_type == "conversion"
        assert event.metric == "roas"
        assert event.value == pytest.approx(4.0, rel=0.01)  # 400/100 = 4.0

    @pytest.mark.asyncio
    async def test_snapshot_returns_economic_snapshot(self):
        """snapshot returns an EconomicSnapshot with all required fields."""
        from apps.economics.economic_intelligence import EconomicIntelligence, EconomicSnapshot

        cache = _mock_cache()
        with patch("apps.economics.economic_intelligence.get_cache", return_value=cache):
            ei = EconomicIntelligence()
            await ei.record_revenue("shopify", 1000.0)
            await ei.record_cost("hosting", 100.0)
            snap = await ei.snapshot("7d")

        assert isinstance(snap, EconomicSnapshot)
        assert snap.snapshot_id is not None
        assert snap.period == "7d"
        assert snap.total_revenue == pytest.approx(1000.0, rel=0.01)
        assert snap.total_costs == pytest.approx(100.0, rel=0.01)
        assert snap.gross_profit == pytest.approx(900.0, rel=0.01)

    @pytest.mark.asyncio
    async def test_snapshot_profit_margin_calculation(self):
        """snapshot correctly calculates profit margin percentage."""
        from apps.economics.economic_intelligence import EconomicIntelligence

        cache = _mock_cache()
        with patch("apps.economics.economic_intelligence.get_cache", return_value=cache):
            ei = EconomicIntelligence()
            await ei.record_revenue("ads", 1000.0)
            await ei.record_cost("ops", 200.0)
            snap = await ei.snapshot("7d")

        # (1000 - 200) / 1000 * 100 = 80%
        assert snap.profit_margin_pct == pytest.approx(80.0, rel=0.01)

    @pytest.mark.asyncio
    async def test_snapshot_identifies_top_revenue_source(self):
        """snapshot identifies the highest revenue source."""
        from apps.economics.economic_intelligence import EconomicIntelligence

        cache = _mock_cache()
        with patch("apps.economics.economic_intelligence.get_cache", return_value=cache):
            ei = EconomicIntelligence()
            await ei.record_revenue("fiverr", 300.0)
            await ei.record_revenue("upwork", 800.0)
            await ei.record_revenue("fiverr", 200.0)
            snap = await ei.snapshot("7d")

        assert snap.top_revenue_source == "upwork"

    @pytest.mark.asyncio
    async def test_prioritize_by_roi_returns_sorted_list(self):
        """prioritize_by_roi returns actions sorted by roi_score descending."""
        from apps.economics.economic_intelligence import EconomicIntelligence

        actions = [
            {"title": "Blog SEO", "estimated_revenue": 500, "estimated_cost": 100},
            {"title": "Paid Ads", "estimated_revenue": 1000, "estimated_cost": 800},
            {"title": "Email Marketing", "estimated_revenue": 2000, "estimated_cost": 50},
        ]

        ai_response = '[{"title": "Email Marketing", "roi_score": 0.95}, {"title": "Blog SEO", "roi_score": 0.8}, {"title": "Paid Ads", "roi_score": 0.3}]'
        cache = _mock_cache()
        ai = _mock_ai(content=ai_response)

        with patch("apps.economics.economic_intelligence.get_cache", return_value=cache), \
             patch("apps.economics.economic_intelligence.get_ai_client", return_value=ai):
            ei = EconomicIntelligence()
            result = await ei.prioritize_by_roi(actions)

        assert isinstance(result, list)
        assert len(result) == 3
        assert all("roi_score" in a for a in result)
        # Should be sorted descending
        scores = [a["roi_score"] for a in result]
        assert scores == sorted(scores, reverse=True)

    @pytest.mark.asyncio
    async def test_prioritize_by_roi_empty_list(self):
        """prioritize_by_roi handles empty input."""
        from apps.economics.economic_intelligence import EconomicIntelligence

        cache = _mock_cache()
        with patch("apps.economics.economic_intelligence.get_cache", return_value=cache):
            ei = EconomicIntelligence()
            result = await ei.prioritize_by_roi([])

        assert result == []

    @pytest.mark.asyncio
    async def test_prioritize_by_roi_fallback_on_ai_failure(self):
        """prioritize_by_roi uses fallback calculation when AI fails."""
        from apps.economics.economic_intelligence import EconomicIntelligence

        actions = [
            {"title": "High ROI Action", "estimated_revenue": 10000, "estimated_cost": 100},
            {"title": "Low ROI Action", "estimated_revenue": 110, "estimated_cost": 100},
        ]

        cache = _mock_cache()
        ai = _mock_ai_failed()

        with patch("apps.economics.economic_intelligence.get_cache", return_value=cache), \
             patch("apps.economics.economic_intelligence.get_ai_client", return_value=ai):
            ei = EconomicIntelligence()
            result = await ei.prioritize_by_roi(actions)

        assert isinstance(result, list)
        assert len(result) == 2
        # High ROI action should come first
        assert result[0]["title"] == "High ROI Action"

    def test_revenue_by_source_sums_correctly(self):
        """revenue_by_source correctly sums revenue per source."""
        from apps.economics.economic_intelligence import EconomicIntelligence
        import time

        ei = EconomicIntelligence()
        ei._loaded = True
        ei._events = [
            {"event_type": "revenue", "source": "shopify", "amount_usd": 500.0, "ts": time.time()},
            {"event_type": "revenue", "source": "shopify", "amount_usd": 300.0, "ts": time.time()},
            {"event_type": "revenue", "source": "fiverr", "amount_usd": 200.0, "ts": time.time()},
            {"event_type": "cost", "source": "shopify", "amount_usd": 100.0, "ts": time.time()},
        ]

        result = ei.revenue_by_source()

        assert result.get("shopify") == pytest.approx(800.0)
        assert result.get("fiverr") == pytest.approx(200.0)
        assert "shopify" in result
        # Cost events should not be counted
        assert result.get("shopify") != 900.0  # Should not include cost

    def test_cost_breakdown_sums_correctly(self):
        """cost_breakdown correctly sums costs per source."""
        from apps.economics.economic_intelligence import EconomicIntelligence
        import time

        ei = EconomicIntelligence()
        ei._loaded = True
        ei._events = [
            {"event_type": "cost", "source": "aws", "amount_usd": 50.0, "ts": time.time()},
            {"event_type": "cost", "source": "aws", "amount_usd": 30.0, "ts": time.time()},
            {"event_type": "cost", "source": "openai", "amount_usd": 10.0, "ts": time.time()},
            {"event_type": "revenue", "source": "aws", "amount_usd": 1000.0, "ts": time.time()},
        ]

        result = ei.cost_breakdown()

        assert result.get("aws") == pytest.approx(80.0)
        assert result.get("openai") == pytest.approx(10.0)

    def test_profitability_report_structure(self):
        """profitability_report returns all required keys."""
        from apps.economics.economic_intelligence import EconomicIntelligence
        import time

        ei = EconomicIntelligence()
        ei._loaded = True
        ei._events = [
            {"event_type": "revenue", "source": "shopify", "amount_usd": 1000.0, "ts": time.time()},
            {"event_type": "cost", "source": "hosting", "amount_usd": 100.0, "ts": time.time()},
        ]

        report = ei.profitability_report()

        assert "total_revenue" in report
        assert "total_costs" in report
        assert "gross_profit" in report
        assert "best_sources" in report
        assert "optimization_opportunities" in report
        assert isinstance(report["best_sources"], list)

    def test_economic_dashboard_returns_complete_data(self):
        """economic_dashboard returns all expected sections."""
        from apps.economics.economic_intelligence import EconomicIntelligence
        import time

        ei = EconomicIntelligence()
        ei._loaded = True
        ei._events = [
            {"event_type": "revenue", "source": "shopify", "amount_usd": 500.0, "ts": time.time()},
            {"event_type": "cost", "source": "ops", "amount_usd": 100.0, "ts": time.time()},
        ]

        dashboard = ei.economic_dashboard()

        assert "summary" in dashboard
        assert "revenue_by_source" in dashboard
        assert "cost_breakdown" in dashboard
        assert "event_counts" in dashboard
        assert "profitability" in dashboard
        assert dashboard["summary"]["total_revenue"] == pytest.approx(500.0)

    def test_recent_events_returns_limited_sorted_list(self):
        """recent_events returns events sorted by timestamp descending."""
        from apps.economics.economic_intelligence import EconomicIntelligence

        ei = EconomicIntelligence()
        ei._loaded = True
        now = time.time()
        ei._events = [
            {"event_type": "revenue", "source": "a", "amount_usd": 100.0, "ts": now - 100},
            {"event_type": "revenue", "source": "b", "amount_usd": 200.0, "ts": now - 50},
            {"event_type": "revenue", "source": "c", "amount_usd": 300.0, "ts": now - 10},
        ]

        recent = ei.recent_events(limit=2)

        assert len(recent) == 2
        assert recent[0]["source"] == "c"  # Most recent first
        assert recent[1]["source"] == "b"

    @pytest.mark.asyncio
    async def test_snapshot_stored_in_snapshots_list(self):
        """snapshot appends to internal _snapshots list."""
        from apps.economics.economic_intelligence import EconomicIntelligence

        cache = _mock_cache()
        with patch("apps.economics.economic_intelligence.get_cache", return_value=cache):
            ei = EconomicIntelligence()
            await ei.snapshot("7d")
            await ei.snapshot("30d")

        assert len(ei._snapshots) == 2

    @pytest.mark.asyncio
    async def test_snapshot_efficiency_score(self):
        """snapshot calculates efficiency_score as revenue/cost ratio."""
        from apps.economics.economic_intelligence import EconomicIntelligence

        cache = _mock_cache()
        with patch("apps.economics.economic_intelligence.get_cache", return_value=cache):
            ei = EconomicIntelligence()
            await ei.record_revenue("x", 1000.0)
            await ei.record_cost("y", 250.0)
            snap = await ei.snapshot("7d")

        assert snap.efficiency_score == pytest.approx(4.0, rel=0.01)  # 1000/250 = 4.0

    @pytest.mark.asyncio
    async def test_record_event_has_uuid_id(self):
        """Each event gets a unique ID."""
        from apps.economics.economic_intelligence import EconomicIntelligence

        cache = _mock_cache()
        with patch("apps.economics.economic_intelligence.get_cache", return_value=cache):
            ei = EconomicIntelligence()
            e1 = await ei.record_event("revenue", "a", 100.0)
            e2 = await ei.record_event("revenue", "b", 200.0)

        assert e1.event_id != e2.event_id


# ══════════════════════════════════════════════════════════════════════════════
# 2. ROITracker
# ══════════════════════════════════════════════════════════════════════════════

class TestROITracker:
    """10+ tests for ROITracker."""

    @pytest.fixture(autouse=True)
    def _reset_singleton(self):
        import apps.economics.roi_tracker as m
        m._instance = None
        yield
        m._instance = None

    @pytest.mark.asyncio
    async def test_track_creates_roi_record(self):
        """track creates a new ROIRecord with correct fields."""
        from apps.economics.roi_tracker import ROITracker, ROIRecord

        cache = _mock_cache()
        with patch("apps.economics.roi_tracker.get_cache", return_value=cache):
            tracker = ROITracker()
            record = await tracker.track("Email Campaign", "campaign", 500.0)

        assert isinstance(record, ROIRecord)
        assert record.record_id is not None
        assert len(record.record_id) > 0
        assert record.name == "Email Campaign"
        assert record.category == "campaign"
        assert record.investment_usd == 500.0
        assert record.status == "tracking"

    @pytest.mark.asyncio
    async def test_track_persists_to_internal_list(self):
        """track appends record to internal _records list."""
        from apps.economics.roi_tracker import ROITracker

        cache = _mock_cache()
        with patch("apps.economics.roi_tracker.get_cache", return_value=cache):
            tracker = ROITracker()
            await tracker.track("Action 1", "action", 100.0)
            await tracker.track("Campaign 2", "campaign", 200.0)

        assert len(tracker._records) == 2

    @pytest.mark.asyncio
    async def test_update_returns_calculates_roi_pct(self):
        """update_returns correctly calculates ROI percentage."""
        from apps.economics.roi_tracker import ROITracker

        cache = _mock_cache()
        with patch("apps.economics.roi_tracker.get_cache", return_value=cache):
            tracker = ROITracker()
            record = await tracker.track("Test Campaign", "campaign", 100.0)
            updated = await tracker.update_returns(record.record_id, 150.0)

        assert updated is not None
        assert updated.returns_usd == 150.0
        # (150 - 100) / 100 * 100 = 50%
        assert updated.roi_pct == pytest.approx(50.0, rel=0.01)

    @pytest.mark.asyncio
    async def test_update_returns_calculates_payback_days(self):
        """update_returns calculates payback_days correctly."""
        from apps.economics.roi_tracker import ROITracker

        cache = _mock_cache()
        with patch("apps.economics.roi_tracker.get_cache", return_value=cache):
            tracker = ROITracker()
            record = await tracker.track("Test", "action", 300.0)
            updated = await tracker.update_returns(record.record_id, 100.0)

        assert updated is not None
        # payback_days = investment / (returns/30) = 300 / (100/30) = 300 / 3.33 = 90
        assert updated.payback_days == pytest.approx(90.0, rel=0.01)

    @pytest.mark.asyncio
    async def test_update_returns_zero_returns_gives_999_payback(self):
        """update_returns with 0 returns yields 999 payback days."""
        from apps.economics.roi_tracker import ROITracker

        cache = _mock_cache()
        with patch("apps.economics.roi_tracker.get_cache", return_value=cache):
            tracker = ROITracker()
            record = await tracker.track("Dead Campaign", "campaign", 100.0)
            updated = await tracker.update_returns(record.record_id, 0.0)

        assert updated is not None
        assert updated.payback_days == 999.0

    @pytest.mark.asyncio
    async def test_update_returns_nonexistent_returns_none(self):
        """update_returns with unknown ID returns None."""
        from apps.economics.roi_tracker import ROITracker

        cache = _mock_cache()
        with patch("apps.economics.roi_tracker.get_cache", return_value=cache):
            tracker = ROITracker()
            result = await tracker.update_returns("nonexistent-id", 100.0)

        assert result is None

    @pytest.mark.asyncio
    async def test_conclude_sets_status_concluded(self):
        """conclude sets status to 'concluded' when returns >= 0."""
        from apps.economics.roi_tracker import ROITracker

        cache = _mock_cache()
        with patch("apps.economics.roi_tracker.get_cache", return_value=cache):
            tracker = ROITracker()
            record = await tracker.track("Experiment", "experiment", 200.0)
            concluded = await tracker.conclude(record.record_id, 400.0)

        assert concluded is not None
        assert concluded.status == "concluded"
        assert concluded.returns_usd == 400.0
        assert concluded.concluded_at > 0

    @pytest.mark.asyncio
    async def test_conclude_sets_status_failed_on_loss(self):
        """conclude sets status to 'failed' when returns < investment (negative ROI)."""
        from apps.economics.roi_tracker import ROITracker

        cache = _mock_cache()
        with patch("apps.economics.roi_tracker.get_cache", return_value=cache):
            tracker = ROITracker()
            record = await tracker.track("Bad Experiment", "experiment", 500.0)
            concluded = await tracker.conclude(record.record_id, 0.0)

        assert concluded is not None
        assert concluded.status == "failed"

    def test_top_roi_records_sorted_desc(self):
        """top_roi_records returns records sorted by ROI descending."""
        from apps.economics.roi_tracker import ROITracker

        tracker = ROITracker()
        tracker._loaded = True
        tracker._records = [
            {"record_id": "a", "name": "Low ROI", "roi_pct": 10.0, "investment_usd": 100.0, "returns_usd": 110.0},
            {"record_id": "b", "name": "High ROI", "roi_pct": 300.0, "investment_usd": 100.0, "returns_usd": 400.0},
            {"record_id": "c", "name": "Medium ROI", "roi_pct": 50.0, "investment_usd": 100.0, "returns_usd": 150.0},
        ]

        top = tracker.top_roi_records(limit=2)

        assert len(top) == 2
        assert top[0]["name"] == "High ROI"
        assert top[1]["name"] == "Medium ROI"

    def test_failed_investments_filters_by_threshold(self):
        """failed_investments returns records below ROI threshold."""
        from apps.economics.roi_tracker import ROITracker

        tracker = ROITracker()
        tracker._loaded = True
        tracker._records = [
            {"record_id": "a", "name": "Good", "roi_pct": 100.0},
            {"record_id": "b", "name": "Bad", "roi_pct": -30.0},
            {"record_id": "c", "name": "Marginal", "roi_pct": -10.0},
            {"record_id": "d", "name": "Terrible", "roi_pct": -50.0},
        ]

        failed = tracker.failed_investments(threshold_roi_pct=-20.0)

        assert len(failed) == 2
        names = {r["name"] for r in failed}
        assert "Bad" in names
        assert "Terrible" in names
        assert "Good" not in names

    def test_roi_summary_complete_structure(self):
        """roi_summary returns all expected keys with correct calculations."""
        from apps.economics.roi_tracker import ROITracker

        tracker = ROITracker()
        tracker._loaded = True
        tracker._records = [
            {"record_id": "a", "name": "Campaign A", "roi_pct": 100.0, "investment_usd": 100.0, "returns_usd": 200.0},
            {"record_id": "b", "name": "Campaign B", "roi_pct": -20.0, "investment_usd": 200.0, "returns_usd": 160.0},
        ]

        summary = tracker.roi_summary()

        assert "total_tracked" in summary
        assert "avg_roi_pct" in summary
        assert "best_roi" in summary
        assert "worst_roi" in summary
        assert "total_returns" in summary
        assert "total_invested" in summary
        assert summary["total_tracked"] == 2
        assert summary["total_returns"] == pytest.approx(360.0)
        assert summary["total_invested"] == pytest.approx(300.0)
        assert summary["avg_roi_pct"] == pytest.approx(40.0, rel=0.01)  # (100 - 20) / 2

    def test_roi_summary_empty_records(self):
        """roi_summary handles empty records list."""
        from apps.economics.roi_tracker import ROITracker

        tracker = ROITracker()
        tracker._loaded = True
        tracker._records = []

        summary = tracker.roi_summary()

        assert summary["total_tracked"] == 0
        assert summary["avg_roi_pct"] == 0.0

    @pytest.mark.asyncio
    async def test_ai_roi_recommendation_calls_ai(self):
        """ai_roi_recommendation calls AI and returns string."""
        from apps.economics.roi_tracker import ROITracker

        cache = _mock_cache()
        ai = _mock_ai("Double down on email marketing — 320% ROI.")

        records = [
            {"name": "Email", "category": "campaign", "roi_pct": 320.0, "investment_usd": 100.0, "returns_usd": 420.0},
        ]

        with patch("apps.economics.roi_tracker.get_cache", return_value=cache), \
             patch("apps.economics.roi_tracker.get_ai_client", return_value=ai):
            tracker = ROITracker()
            result = await tracker.ai_roi_recommendation(records)

        assert isinstance(result, str)
        assert len(result) > 0

    @pytest.mark.asyncio
    async def test_ai_roi_recommendation_empty_returns_message(self):
        """ai_roi_recommendation with empty records returns fallback message."""
        from apps.economics.roi_tracker import ROITracker

        cache = _mock_cache()
        with patch("apps.economics.roi_tracker.get_cache", return_value=cache):
            tracker = ROITracker()
            result = await tracker.ai_roi_recommendation([])

        assert isinstance(result, str)
        assert len(result) > 0

    def test_roi_record_multiple_calculation(self):
        """ROIRecord.roi_multiple returns returns/investment ratio."""
        from apps.economics.roi_tracker import ROIRecord

        record = ROIRecord(
            name="Test",
            investment_usd=100.0,
            returns_usd=350.0,
        )

        assert record.roi_multiple() == pytest.approx(3.5, rel=0.01)
