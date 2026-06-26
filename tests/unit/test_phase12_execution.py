"""Phase 12 tests — Daily Execution Runtime (DailyRuntime)."""
from __future__ import annotations
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def _mock_cache():
    c = MagicMock()
    c.get = AsyncMock(return_value=None)
    c.set = AsyncMock(return_value=True)
    return c


def _mock_ai(content="Focus on content that converts\nDouble outreach volume\nOptimize highest-traffic landing page\nTrack what content drives sales\nTest SMS for cart recovery\nScale what works"):
    ai = MagicMock()
    r = MagicMock()
    r.success = True
    r.content = content
    ai.complete = AsyncMock(return_value=r)
    return ai


class TestDailyRuntime:
    @pytest.fixture
    def runtime(self):
        with patch("apps.execution.daily_runtime.get_cache", return_value=_mock_cache()):
            with patch("apps.execution.daily_runtime.get_ai_client", return_value=_mock_ai()):
                from apps.execution.daily_runtime import DailyRuntime
                return DailyRuntime()

    # ── plan_day ─────────────────────────────────────────────────────────────

    def test_plan_day_returns_list(self, runtime):
        tasks = runtime.plan_day()
        assert isinstance(tasks, list)

    def test_plan_day_has_tasks(self, runtime):
        tasks = runtime.plan_day()
        assert len(tasks) >= 10

    def test_plan_day_tasks_are_daily_task(self, runtime):
        from apps.execution.daily_runtime import DailyTask
        tasks = runtime.plan_day()
        assert all(isinstance(t, DailyTask) for t in tasks)

    def test_plan_day_sorted_by_priority(self, runtime):
        tasks = runtime.plan_day()
        priorities = [t.priority for t in tasks]
        assert priorities == sorted(priorities)

    def test_plan_day_tasks_have_name(self, runtime):
        tasks = runtime.plan_day()
        assert all(len(t.name) > 0 for t in tasks)

    def test_plan_day_tasks_have_system(self, runtime):
        tasks = runtime.plan_day()
        valid_systems = {"content", "acquisition", "shopify", "conversion", "market", "memory"}
        assert all(t.system in valid_systems for t in tasks)

    def test_plan_day_tasks_start_as_pending(self, runtime):
        tasks = runtime.plan_day()
        assert all(t.status == "pending" for t in tasks)

    def test_plan_day_has_priority_1_tasks(self, runtime):
        tasks = runtime.plan_day()
        p1_tasks = [t for t in tasks if t.priority == 1]
        assert len(p1_tasks) >= 2

    def test_plan_day_covers_all_systems(self, runtime):
        tasks = runtime.plan_day()
        systems = {t.system for t in tasks}
        assert "content" in systems
        assert "acquisition" in systems
        assert "shopify" in systems

    # ── execute_task ──────────────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_execute_task_sets_status(self, runtime):
        tasks = runtime.plan_day()
        task = tasks[0]
        result_task = await runtime.execute_task(task)
        assert result_task.status in ("done", "failed")

    @pytest.mark.asyncio
    async def test_execute_task_sets_started_at(self, runtime):
        task = runtime.plan_day()[0]
        result_task = await runtime.execute_task(task)
        assert result_task.started_at > 0

    @pytest.mark.asyncio
    async def test_execute_task_sets_completed_at(self, runtime):
        task = runtime.plan_day()[0]
        result_task = await runtime.execute_task(task)
        assert result_task.completed_at >= result_task.started_at

    @pytest.mark.asyncio
    async def test_execute_task_sets_duration(self, runtime):
        task = runtime.plan_day()[0]
        result_task = await runtime.execute_task(task)
        assert result_task.duration_seconds >= 0.0

    @pytest.mark.asyncio
    async def test_execute_task_has_result_dict(self, runtime):
        task = runtime.plan_day()[0]
        result_task = await runtime.execute_task(task)
        assert isinstance(result_task.result, dict)

    # ── run_daily ─────────────────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_run_daily_returns_report(self, runtime):
        from apps.execution.daily_runtime import DailyReport
        report = await runtime.run_daily(max_tasks=3)
        assert isinstance(report, DailyReport)
        assert report.report_id

    @pytest.mark.asyncio
    async def test_run_daily_has_date(self, runtime):
        report = await runtime.run_daily(max_tasks=2)
        assert len(report.date) == 10  # YYYY-MM-DD
        assert "-" in report.date

    @pytest.mark.asyncio
    async def test_run_daily_tasks_planned(self, runtime):
        report = await runtime.run_daily(max_tasks=5)
        assert report.tasks_planned == 5

    @pytest.mark.asyncio
    async def test_run_daily_tasks_completed_plus_failed_equals_planned(self, runtime):
        report = await runtime.run_daily(max_tasks=4)
        assert report.tasks_completed + report.tasks_failed == report.tasks_planned

    @pytest.mark.asyncio
    async def test_run_daily_has_execution_score(self, runtime):
        report = await runtime.run_daily(max_tasks=3)
        assert 0.0 <= report.execution_score <= 1.0

    @pytest.mark.asyncio
    async def test_run_daily_has_revenue_actions(self, runtime):
        report = await runtime.run_daily(max_tasks=5)
        assert isinstance(report.revenue_actions, list)

    @pytest.mark.asyncio
    async def test_run_daily_has_insights(self, runtime):
        report = await runtime.run_daily(max_tasks=2)
        assert isinstance(report.insights, list)
        assert len(report.insights) >= 1

    @pytest.mark.asyncio
    async def test_run_daily_has_next_priorities(self, runtime):
        report = await runtime.run_daily(max_tasks=2)
        assert isinstance(report.next_priorities, list)
        assert len(report.next_priorities) >= 1

    @pytest.mark.asyncio
    async def test_run_daily_stores_tasks(self, runtime):
        await runtime.run_daily(max_tasks=3)
        assert len(runtime._tasks) == 3

    @pytest.mark.asyncio
    async def test_run_daily_stores_report(self, runtime):
        await runtime.run_daily(max_tasks=2)
        assert len(runtime._reports) == 1

    # ── generate_report ───────────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_generate_report_returns_report(self, runtime):
        from apps.execution.daily_runtime import DailyReport
        report = await runtime.generate_report()
        assert isinstance(report, DailyReport)

    @pytest.mark.asyncio
    async def test_generate_report_has_date(self, runtime):
        report = await runtime.generate_report()
        assert len(report.date) > 0

    @pytest.mark.asyncio
    async def test_generate_report_has_insights(self, runtime):
        report = await runtime.generate_report()
        assert len(report.insights) >= 1

    @pytest.mark.asyncio
    async def test_generate_report_has_next_priorities(self, runtime):
        report = await runtime.generate_report()
        assert len(report.next_priorities) >= 1

    @pytest.mark.asyncio
    async def test_generate_report_stores_in_reports(self, runtime):
        await runtime.generate_report()
        assert len(runtime._reports) == 1

    # ── runtime_stats ─────────────────────────────────────────────────────────

    def test_runtime_stats_has_required_keys(self, runtime):
        stats = runtime.runtime_stats()
        assert "total_tasks_executed" in stats
        assert "success_rate_pct" in stats
        assert "by_system" in stats
        assert "total_reports" in stats
        assert "plan_size" in stats

    def test_runtime_stats_plan_size_positive(self, runtime):
        stats = runtime.runtime_stats()
        assert stats["plan_size"] >= 10

    @pytest.mark.asyncio
    async def test_runtime_stats_reflects_execution(self, runtime):
        await runtime.run_daily(max_tasks=3)
        stats = runtime.runtime_stats()
        assert stats["total_tasks_executed"] == 3
        assert stats["total_reports"] == 1

    def test_recent_reports_returns_list(self, runtime):
        result = runtime.recent_reports(limit=7)
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_recent_reports_after_run(self, runtime):
        await runtime.run_daily(max_tasks=2)
        result = runtime.recent_reports(limit=7)
        assert len(result) >= 1

    # ── DailyReport.to_dict ───────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_report_to_dict_has_required_keys(self, runtime):
        report = await runtime.run_daily(max_tasks=2)
        d = report.to_dict()
        required = {"report_id", "date", "tasks_planned", "tasks_completed", "tasks_failed",
                    "revenue_actions", "content_pieces", "leads_contacted", "optimizations_run",
                    "insights", "next_priorities", "execution_score", "created_at"}
        assert required.issubset(d.keys())

    # ── DailyTask.to_dict ─────────────────────────────────────────────────────

    def test_daily_task_to_dict_has_required_keys(self, runtime):
        task = runtime.plan_day()[0]
        d = task.to_dict()
        required = {"task_id", "name", "system", "action", "priority", "status",
                    "result", "started_at", "completed_at", "duration_seconds", "error"}
        assert required.issubset(d.keys())

    @pytest.mark.asyncio
    async def test_multiple_runs_accumulate_reports(self, runtime):
        await runtime.run_daily(max_tasks=1)
        await runtime.generate_report()
        assert len(runtime._reports) == 2
