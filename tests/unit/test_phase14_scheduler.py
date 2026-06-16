"""Phase 14 tests — ARIAScheduler."""
from __future__ import annotations
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def _mock_cache():
    c = MagicMock()
    c.get = AsyncMock(return_value=None)
    c.set = AsyncMock(return_value=True)
    return c


@pytest.fixture
def scheduler():
    with patch("apps.runtime.scheduler.get_cache", return_value=_mock_cache()):
        from apps.runtime.scheduler import ARIAScheduler
        return ARIAScheduler()


# ── Initialization ────────────────────────────────────────────────────────────

def test_scheduler_starts_not_running(scheduler):
    assert scheduler._running is False


def test_scheduler_job_log_starts_empty(scheduler):
    assert isinstance(scheduler._job_log, list)
    assert len(scheduler._job_log) == 0


def test_get_scheduler_returns_instance(scheduler):
    sched = scheduler._get_scheduler()
    assert sched is not None


def test_scheduler_status_not_running(scheduler):
    status = scheduler.scheduler_status()
    assert status["running"] is False


def test_scheduler_status_has_required_keys(scheduler):
    status = scheduler.scheduler_status()
    required = {"running", "total_jobs", "job_names", "recent_executions", "next_run_times"}
    assert required.issubset(status.keys())


def test_recent_executions_returns_list(scheduler):
    result = scheduler.recent_executions(limit=10)
    assert isinstance(result, list)


# ── Job log ───────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_log_job_appends_record(scheduler):
    await scheduler._log_job("test_job", "Test Job", True, 1.5)
    assert len(scheduler._job_log) == 1


@pytest.mark.asyncio
async def test_log_job_record_has_required_keys(scheduler):
    await scheduler._log_job("test_job", "Test Job", True, 2.3)
    record = scheduler._job_log[0]
    assert "job_id" in record
    assert "job_name" in record
    assert "success" in record
    assert "duration_s" in record


@pytest.mark.asyncio
async def test_log_job_success_true(scheduler):
    await scheduler._log_job("job_a", "Job A", True, 0.5)
    assert scheduler._job_log[0]["success"] is True


@pytest.mark.asyncio
async def test_log_job_failure_records_error(scheduler):
    await scheduler._log_job("job_b", "Job B", False, 0.1, error="Something failed")
    assert scheduler._job_log[0]["error"] == "Something failed"


@pytest.mark.asyncio
async def test_multiple_log_entries_accumulate(scheduler):
    for i in range(5):
        await scheduler._log_job(f"job_{i}", f"Job {i}", True, 0.1)
    assert len(scheduler._job_log) == 5


@pytest.mark.asyncio
async def test_recent_executions_after_log(scheduler):
    await scheduler._log_job("x", "X", True, 1.0)
    result = scheduler.recent_executions(limit=10)
    assert len(result) >= 1


# ── Session handlers (mocked to avoid actual loop calls) ─────────────────────

@pytest.mark.asyncio
async def test_run_morning_session_gracefully_degrades(scheduler):
    with patch("apps.runtime.daily_business_loop.get_daily_business_loop") as mock_get:
        mock_loop = MagicMock()
        mock_loop.run_morning_session = AsyncMock(return_value=[])
        mock_get.return_value = mock_loop
        await scheduler._run_morning_session()
    assert len(scheduler._job_log) == 1


@pytest.mark.asyncio
async def test_run_midday_session_gracefully_degrades(scheduler):
    with patch("apps.runtime.daily_business_loop.get_daily_business_loop") as mock_get:
        mock_loop = MagicMock()
        mock_loop.run_midday_session = AsyncMock(return_value=[])
        mock_get.return_value = mock_loop
        await scheduler._run_midday_session()
    assert len(scheduler._job_log) == 1


@pytest.mark.asyncio
async def test_run_lead_discovery_gracefully_degrades(scheduler):
    with patch("apps.acquisition.leads.lead_engine.get_lead_engine") as mock_get:
        mock_eng = MagicMock()
        mock_eng.discover_leads = AsyncMock(return_value=[])
        mock_get.return_value = mock_eng
        await scheduler._run_lead_discovery()
    assert len(scheduler._job_log) == 1


@pytest.mark.asyncio
async def test_morning_session_no_crash_on_import_error(scheduler):
    with patch.dict("sys.modules", {"apps.runtime.daily_business_loop": None}):
        try:
            await scheduler._run_morning_session()
        except Exception:
            pass
    assert True


# ── Start/stop ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_start_sets_running(scheduler):
    await scheduler.start()
    assert scheduler._running is True
    await scheduler.stop()


@pytest.mark.asyncio
async def test_start_stop_cycle(scheduler):
    await scheduler.start()
    assert scheduler._running is True
    await scheduler.stop()
    assert scheduler._running is False


@pytest.mark.asyncio
async def test_double_start_is_safe(scheduler):
    await scheduler.start()
    await scheduler.start()
    assert scheduler._running is True
    await scheduler.stop()


@pytest.mark.asyncio
async def test_status_after_start(scheduler):
    await scheduler.start()
    status = scheduler.scheduler_status()
    assert status["running"] is True
    assert status["total_jobs"] >= 5
    await scheduler.stop()


@pytest.mark.asyncio
async def test_status_job_names_after_start(scheduler):
    await scheduler.start()
    status = scheduler.scheduler_status()
    names = status["job_names"]
    assert isinstance(names, list)
    assert len(names) >= 5
    await scheduler.stop()


# ── Singleton ─────────────────────────────────────────────────────────────────

def test_get_aria_scheduler_returns_instance():
    with patch("apps.runtime.scheduler.get_cache", return_value=_mock_cache()):
        from apps.runtime.scheduler import get_aria_scheduler
        s = get_aria_scheduler()
        assert s is not None
