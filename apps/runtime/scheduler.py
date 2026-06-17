"""
ARIA Autonomous Scheduler — APScheduler-based persistent cron.

Runs daily business operations on schedule:
  - Morning session: 09:00 UTC daily
  - Midday session: 13:00 UTC daily
  - Full daily loop: 17:00 UTC daily
  - Economic analytics refresh: every 6 hours
  - Lead discovery: every 12 hours

State persisted in Redis so schedule survives restarts.
Start with: asyncio.run(start_scheduler()) or as background task.
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from apps.core.memory.redis_client import get_cache

logger = logging.getLogger(__name__)

_SCHEDULER_KEY = "runtime:scheduler:v1"
_SCHEDULER_TTL = 86400 * 90


@dataclass
class JobRecord:
    record_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    job_id: str = ""
    job_name: str = ""
    success: bool = False
    duration_s: float = 0.0
    error: str = ""
    ts: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "record_id": self.record_id,
            "job_id": self.job_id,
            "job_name": self.job_name,
            "success": self.success,
            "duration_s": round(self.duration_s, 3),
            "error": self.error,
            "ts": self.ts,
        }


class ARIAScheduler:
    """
    APScheduler-based persistent cron for ARIA's daily business operations.

    Schedules and tracks all autonomous jobs; persists execution log to Redis
    so state survives process restarts.
    """

    def __init__(self) -> None:
        self._scheduler: Optional[AsyncIOScheduler] = None
        self._job_log: list[dict] = []
        self._running: bool = False

    # ── Lazy scheduler init ─────────────────────────────────────────────

    def _get_scheduler(self) -> AsyncIOScheduler:
        if self._scheduler is None:
            self._scheduler = AsyncIOScheduler(timezone="UTC")
        return self._scheduler

    # ── Job log persistence ────────────────────────────────────────────

    async def _log_job(
        self,
        job_id: str,
        job_name: str,
        success: bool,
        duration_s: float,
        error: str = "",
    ) -> None:
        record = JobRecord(
            job_id=job_id,
            job_name=job_name,
            success=success,
            duration_s=duration_s,
            error=error,
        )
        self._job_log.append(record.to_dict())
        # Keep at most 200 records in memory
        if len(self._job_log) > 200:
            self._job_log = self._job_log[-200:]

        try:
            cache = get_cache()
            await cache.set(
                _SCHEDULER_KEY,
                {"job_log": self._job_log},
                ttl_seconds=_SCHEDULER_TTL,
            )
        except Exception as exc:
            logger.warning("ARIAScheduler: could not persist job log: %s", exc)

    # ── Scheduled job handlers ──────────────────────────────────────────

    async def _run_morning_session(self) -> None:
        job_name = "morning_session"
        start = time.time()
        try:
            from apps.runtime.daily_business_loop import get_daily_business_loop  # noqa: PLC0415

            loop = get_daily_business_loop()
            ops = await loop.run_morning_session()
            done = sum(1 for op in ops if op.status == "done")
            logger.info("ARIAScheduler [morning]: %d/%d ops done", done, len(ops))
            await self._log_job(job_name, "Morning Business Session", True, time.time() - start)
        except Exception as exc:
            logger.error("ARIAScheduler [morning] failed: %s", exc)
            await self._log_job(
                job_name, "Morning Business Session", False, time.time() - start, str(exc)
            )

    async def _run_midday_session(self) -> None:
        job_name = "midday_session"
        start = time.time()
        try:
            from apps.runtime.daily_business_loop import get_daily_business_loop  # noqa: PLC0415

            loop = get_daily_business_loop()
            ops = await loop.run_midday_session()
            done = sum(1 for op in ops if op.status == "done")
            logger.info("ARIAScheduler [midday]: %d/%d ops done", done, len(ops))
            await self._log_job(job_name, "Midday Business Session", True, time.time() - start)
        except Exception as exc:
            logger.error("ARIAScheduler [midday] failed: %s", exc)
            await self._log_job(
                job_name, "Midday Business Session", False, time.time() - start, str(exc)
            )

    async def _run_full_daily_loop(self) -> None:
        job_name = "full_daily_loop"
        start = time.time()
        try:
            from apps.runtime.daily_business_loop import get_daily_business_loop  # noqa: PLC0415

            loop = get_daily_business_loop()
            report = await loop.run(max_ops=18)
            logger.info(
                "ARIAScheduler [daily]: score=%.1f%% (%d/%d ops)",
                report.execution_score * 100,
                report.ops_completed,
                report.ops_total,
            )
            # Persist report summary
            try:
                cache = get_cache()
                await cache.set(
                    "runtime:last_daily_report:v1",
                    report.to_dict(),
                    ttl_seconds=86400 * 7,
                )
            except Exception as cache_exc:
                logger.warning("ARIAScheduler: could not cache daily report: %s", cache_exc)

            await self._log_job(job_name, "Full Daily Business Loop", True, time.time() - start)
        except Exception as exc:
            logger.error("ARIAScheduler [daily_loop] failed: %s", exc)
            await self._log_job(
                job_name, "Full Daily Business Loop", False, time.time() - start, str(exc)
            )

    async def _run_lead_discovery(self) -> None:
        job_name = "lead_discovery"
        start = time.time()
        try:
            from apps.acquisition.leads.lead_engine import get_lead_engine  # noqa: PLC0415

            engine = get_lead_engine()
            leads = await engine.discover_leads("ecommerce", count=5)
            logger.info("ARIAScheduler [leads]: discovered %d leads", len(leads))
            await self._log_job(
                job_name,
                "Lead Discovery",
                True,
                time.time() - start,
            )
        except Exception as exc:
            logger.error("ARIAScheduler [lead_discovery] failed: %s", exc)
            await self._log_job(
                job_name, "Lead Discovery", False, time.time() - start, str(exc)
            )

    async def _run_autonomous_objectives(self) -> None:
        job_name = "autonomous_objectives"
        start = time.time()
        try:
            from apps.runtime.autonomy.autonomous_scheduler import get_autonomous_scheduler  # noqa: PLC0415

            sched = get_autonomous_scheduler()
            results = await sched.run_due_objectives()
            done = sum(1 for r in results if r.success)
            logger.info("ARIAScheduler [autonomous]: %d/%d objectives ran", done, len(results))
            await self._log_job(job_name, "Autonomous Strategic Objectives", True, time.time() - start)
        except Exception as exc:
            logger.error("ARIAScheduler [autonomous] failed: %s", exc)
            await self._log_job(
                job_name, "Autonomous Strategic Objectives", False, time.time() - start, str(exc)
            )

    async def _run_analytics_refresh(self) -> None:
        job_name = "analytics_refresh"
        start = time.time()
        try:
            from apps.economics.economic_intelligence import get_economic_intelligence  # noqa: PLC0415

            intel = get_economic_intelligence()
            await intel._load()
            # Cache a lightweight signal so the dashboard can read it cheaply
            dashboard = intel.economic_dashboard()
            cache = get_cache()
            await cache.set(
                "economics:dashboard:refresh:v1",
                dashboard,
                ttl_seconds=86400,
            )
            logger.info("ARIAScheduler [analytics]: dashboard refreshed")
            await self._log_job(job_name, "Economic Analytics Refresh", True, time.time() - start)
        except ImportError as exc:
            # Gracefully degrade if economics module is absent or not yet wired
            logger.warning("ARIAScheduler [analytics]: module unavailable — %s", exc)
            await self._log_job(
                job_name, "Economic Analytics Refresh", False, time.time() - start, str(exc)
            )
        except Exception as exc:
            logger.error("ARIAScheduler [analytics] failed: %s", exc)
            await self._log_job(
                job_name, "Economic Analytics Refresh", False, time.time() - start, str(exc)
            )

    # ── Lifecycle ──────────────────────────────────────────────────

    async def start(self) -> None:
        if self._running:
            logger.info("ARIAScheduler: already running — skipping start")
            return

        # Restore job log from Redis
        try:
            cache = get_cache()
            data = await cache.get(_SCHEDULER_KEY)
            if isinstance(data, dict):
                self._job_log = data.get("job_log", [])
                logger.info(
                    "ARIAScheduler: restored %d job records from Redis", len(self._job_log)
                )
        except Exception as exc:
            logger.warning("ARIAScheduler: could not load state from Redis: %s", exc)

        scheduler = self._get_scheduler()

        # Daily time-based jobs
        scheduler.add_job(
            self._run_morning_session,
            trigger=CronTrigger(hour=9, minute=0, timezone="UTC"),
            id="morning_session",
            name="Morning Business Session",
            replace_existing=True,
            misfire_grace_time=3600,
        )
        scheduler.add_job(
            self._run_midday_session,
            trigger=CronTrigger(hour=13, minute=0, timezone="UTC"),
            id="midday_session",
            name="Midday Business Session",
            replace_existing=True,
            misfire_grace_time=3600,
        )
        scheduler.add_job(
            self._run_full_daily_loop,
            trigger=CronTrigger(hour=17, minute=0, timezone="UTC"),
            id="full_daily_loop",
            name="Full Daily Business Loop",
            replace_existing=True,
            misfire_grace_time=3600,
        )

        # Interval-based jobs
        scheduler.add_job(
            self._run_lead_discovery,
            trigger=IntervalTrigger(hours=12),
            id="lead_discovery",
            name="Lead Discovery",
            replace_existing=True,
            misfire_grace_time=1800,
        )
        scheduler.add_job(
            self._run_analytics_refresh,
            trigger=IntervalTrigger(hours=6),
            id="analytics_refresh",
            name="Economic Analytics Refresh",
            replace_existing=True,
            misfire_grace_time=900,
        )
        scheduler.add_job(
            self._run_autonomous_objectives,
            trigger=IntervalTrigger(hours=1),
            id="autonomous_objectives",
            name="Autonomous Strategic Objectives",
            replace_existing=True,
            misfire_grace_time=1800,
        )

        scheduler.start()
        self._running = True
        logger.info("ARIAScheduler: started with %d jobs", len(scheduler.get_jobs()))

        # Persist startup record
        try:
            cache = get_cache()
            await cache.set(
                "runtime:scheduler:startup:v1",
                {
                    "started_at": time.time(),
                    "jobs": [j.id for j in scheduler.get_jobs()],
                },
                ttl_seconds=_SCHEDULER_TTL,
            )
        except Exception as exc:
            logger.warning("ARIAScheduler: could not log startup: %s", exc)

    async def stop(self) -> None:
        if self._running:
            try:
                self._get_scheduler().shutdown(wait=False)
            except Exception as exc:
                logger.warning("ARIAScheduler: error during shutdown: %s", exc)
            self._running = False
            logger.info("ARIAScheduler: stopped")

    # ── Status / introspection ──────────────────────────────────────────

    def scheduler_status(self) -> dict:
        scheduler = self._get_scheduler()
        jobs = scheduler.get_jobs() if self._running else []

        next_run_times: dict[str, str] = {}
        for job in jobs:
            nrt = job.next_run_time
            next_run_times[job.id] = str(nrt) if nrt else "not scheduled"

        return {
            "running": self._running,
            "total_jobs": len(jobs),
            "job_names": [j.name for j in jobs],
            "recent_executions": self._job_log[-10:] if self._job_log else [],
            "next_run_times": next_run_times,
        }

    def recent_executions(self, limit: int = 20) -> list[dict]:
        return self._job_log[-limit:] if self._job_log else []


# ── Singleton ─────────────────────────────────────────────────────

_scheduler_instance: ARIAScheduler | None = None


def get_aria_scheduler() -> ARIAScheduler:
    global _scheduler_instance
    if _scheduler_instance is None:
        _scheduler_instance = ARIAScheduler()
    return _scheduler_instance
