"""Phase 13 tests — Daily Business Loop (DailyBusinessLoop)."""
from __future__ import annotations
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def _mock_cache():
    c = MagicMock()
    c.get = AsyncMock(return_value=None)
    c.set = AsyncMock(return_value=True)
    return c


def _mock_ai(content="Execution consistency drives compound growth over time.\nIncrease outreach volume by 50% tomorrow."):
    ai = MagicMock()
    r = MagicMock()
    r.success = True
    r.content = content
    ai.complete = AsyncMock(return_value=r)
    return ai


class TestDailyBusinessLoop:
    @pytest.fixture
    def loop(self):
        with patch("apps.runtime.daily_business_loop.get_cache", return_value=_mock_cache()):
            with patch("apps.runtime.daily_business_loop.get_ai_client", return_value=_mock_ai()):
                from apps.runtime.daily_business_loop import DailyBusinessLoop
                return DailyBusinessLoop()

    # ── build_daily_ops ───────────────────────────────────────────────────────

    def test_build_daily_ops_returns_list(self, loop):
        ops = loop.build_daily_ops()
        assert isinstance(ops, list)

    def test_build_daily_ops_has_ops(self, loop):
        ops = loop.build_daily_ops()
        assert len(ops) >= 15

    def test_build_daily_ops_are_business_operations(self, loop):
        from apps.runtime.daily_business_loop import BusinessOperation
        ops = loop.build_daily_ops()
        assert all(isinstance(op, BusinessOperation) for op in ops)

    def test_build_daily_ops_have_names(self, loop):
        ops = loop.build_daily_ops()
        assert all(len(op.name) > 0 for op in ops)

    def test_build_daily_ops_have_categories(self, loop):
        ops = loop.build_daily_ops()
        valid = {"distribution", "acquisition", "shopify", "conversion", "market", "learning", "planning"}
        assert all(op.category in valid for op in ops)

    def test_build_daily_ops_start_as_pending(self, loop):
        ops = loop.build_daily_ops()
        assert all(op.status == "pending" for op in ops)

    def test_build_daily_ops_cover_distribution(self, loop):
        ops = loop.build_daily_ops()
        assert any(op.category == "distribution" for op in ops)

    def test_build_daily_ops_cover_acquisition(self, loop):
        ops = loop.build_daily_ops()
        assert any(op.category == "acquisition" for op in ops)

    def test_build_daily_ops_cover_shopify(self, loop):
        ops = loop.build_daily_ops()
        assert any(op.category == "shopify" for op in ops)

    def test_build_daily_ops_have_revenue_impact(self, loop):
        ops = loop.build_daily_ops()
        valid = {"direct", "indirect", "learning"}
        assert all(op.revenue_impact in valid for op in ops)

    def test_build_daily_ops_has_direct_impact_ops(self, loop):
        ops = loop.build_daily_ops()
        direct = [op for op in ops if op.revenue_impact == "direct"]
        assert len(direct) >= 5

    # ── execute_operation ─────────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_execute_op_sets_status(self, loop):
        ops = loop.build_daily_ops()
        op = await loop.execute_operation(ops[0])
        assert op.status in ("done", "failed")

    @pytest.mark.asyncio
    async def test_execute_op_sets_started_at(self, loop):
        op = loop.build_daily_ops()[0]
        result = await loop.execute_operation(op)
        assert result.started_at > 0

    @pytest.mark.asyncio
    async def test_execute_op_sets_completed_at(self, loop):
        op = loop.build_daily_ops()[0]
        result = await loop.execute_operation(op)
        assert result.completed_at >= result.started_at

    @pytest.mark.asyncio
    async def test_execute_op_sets_duration(self, loop):
        op = loop.build_daily_ops()[0]
        result = await loop.execute_operation(op)
        assert result.duration_seconds >= 0.0

    @pytest.mark.asyncio
    async def test_execute_op_stores_in_history(self, loop):
        await loop._load()
        op = loop.build_daily_ops()[0]
        await loop.execute_operation(op)
        assert len(loop._op_history) == 1

    # ── run ───────────────────────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_run_returns_report(self, loop):
        from apps.runtime.daily_business_loop import DailyBusinessReport
        report = await loop.run(max_ops=3)
        assert isinstance(report, DailyBusinessReport)
        assert report.report_id

    @pytest.mark.asyncio
    async def test_run_has_date(self, loop):
        report = await loop.run(max_ops=2)
        assert len(report.date) == 10
        assert "-" in report.date

    @pytest.mark.asyncio
    async def test_run_ops_total_matches_max(self, loop):
        report = await loop.run(max_ops=5)
        assert report.ops_total == 5

    @pytest.mark.asyncio
    async def test_run_completed_plus_failed_equals_total(self, loop):
        report = await loop.run(max_ops=4)
        assert report.ops_completed + report.ops_failed == report.ops_total

    @pytest.mark.asyncio
    async def test_run_has_execution_score(self, loop):
        report = await loop.run(max_ops=3)
        assert 0.0 <= report.execution_score <= 1.0

    @pytest.mark.asyncio
    async def test_run_has_top_insight(self, loop):
        report = await loop.run(max_ops=2)
        assert len(report.top_insight) > 0

    @pytest.mark.asyncio
    async def test_run_has_tomorrow_priority(self, loop):
        report = await loop.run(max_ops=2)
        assert len(report.tomorrow_priority) > 0

    @pytest.mark.asyncio
    async def test_run_stores_report(self, loop):
        await loop.run(max_ops=2)
        assert len(loop._reports) == 1

    @pytest.mark.asyncio
    async def test_run_morning_session_returns_list(self, loop):
        ops = await loop.run_morning_session()
        assert isinstance(ops, list)
        assert len(ops) > 0

    @pytest.mark.asyncio
    async def test_run_morning_session_ops_are_done_or_failed(self, loop):
        ops = await loop.run_morning_session()
        assert all(op.status in ("done", "failed") for op in ops)

    @pytest.mark.asyncio
    async def test_run_midday_session_returns_list(self, loop):
        ops = await loop.run_midday_session()
        assert isinstance(ops, list)
        assert len(ops) > 0

    # ── generate_status_report ────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_generate_status_report_returns_dict(self, loop):
        report = await loop.generate_status_report()
        assert isinstance(report, dict)

    @pytest.mark.asyncio
    async def test_generate_status_report_has_required_keys(self, loop):
        report = await loop.generate_status_report()
        assert "date" in report
        assert "ops_today" in report
        assert "ops_done" in report
        assert "execution_score" in report
        assert "total_reports" in report

    # ── loop_stats ────────────────────────────────────────────────────────────

    def test_loop_stats_has_required_keys(self, loop):
        stats = loop.loop_stats()
        assert "total_ops_executed" in stats
        assert "success_rate_pct" in stats
        assert "total_reports" in stats
        assert "by_category" in stats
        assert "daily_op_count" in stats

    def test_loop_stats_daily_op_count_positive(self, loop):
        stats = loop.loop_stats()
        assert stats["daily_op_count"] >= 15

    @pytest.mark.asyncio
    async def test_loop_stats_reflect_execution(self, loop):
        await loop.run(max_ops=3)
        stats = loop.loop_stats()
        assert stats["total_ops_executed"] == 3
        assert stats["total_reports"] == 1

    def test_recent_reports_returns_list(self, loop):
        result = loop.recent_reports(limit=7)
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_recent_reports_after_run(self, loop):
        await loop.run(max_ops=2)
        result = loop.recent_reports(limit=7)
        assert len(result) >= 1

    # ── BusinessOperation.to_dict ─────────────────────────────────────────────

    def test_business_operation_to_dict_has_required_keys(self, loop):
        from apps.runtime.daily_business_loop import BusinessOperation
        op = BusinessOperation(name="Test", category="distribution", revenue_impact="direct")
        d = op.to_dict()
        required = {"op_id", "name", "category", "revenue_impact", "status",
                    "result", "started_at", "completed_at", "duration_seconds", "error"}
        assert required.issubset(d.keys())

    # ── DailyBusinessReport.to_dict ───────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_report_to_dict_has_required_keys(self, loop):
        report = await loop.run(max_ops=2)
        d = report.to_dict()
        required = {
            "report_id", "date", "ops_total", "ops_completed", "ops_failed",
            "direct_revenue_ops", "content_pieces_generated", "leads_discovered",
            "outreach_sent", "shopify_optimizations", "funnels_optimized",
            "top_insight", "tomorrow_priority", "execution_score", "created_at",
        }
        assert required.issubset(d.keys())

    @pytest.mark.asyncio
    async def test_multiple_runs_accumulate_reports(self, loop):
        await loop.run(max_ops=2)
        await loop.run(max_ops=2)
        assert len(loop._reports) == 2
