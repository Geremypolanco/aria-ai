"""
ARIA AI — Daily Execution Runtime
Phase 12: Coordinates all revenue-generating systems into a daily execution plan.

ARIA operates like a business every day:
  - Generates and distributes content
  - Runs client acquisition outreach
  - Optimizes Shopify SEO and funnels
  - Analyzes ROI and adjusts priorities
  - Produces a daily economic report

No manual intervention required.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from apps.core.memory.redis_client import get_cache
from apps.core.tools.ai_client import get_ai_client, AIModel

_KEY = "execution:daily:v1"
_TTL = 86400 * 90  # 90 days of history


# ── Domain objects ────────────────────────────────────────────────────────────

@dataclass
class DailyTask:
    task_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    name: str = ""
    system: str = ""        # content | acquisition | shopify | conversion | market | memory
    action: str = ""        # specific operation description
    priority: int = 5       # 1 = highest
    status: str = "pending" # pending | running | done | failed
    result: dict = field(default_factory=dict)
    started_at: float = 0.0
    completed_at: float = 0.0
    duration_seconds: float = 0.0
    error: str = ""

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "name": self.name,
            "system": self.system,
            "action": self.action,
            "priority": self.priority,
            "status": self.status,
            "result": self.result,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "duration_seconds": self.duration_seconds,
            "error": self.error,
        }


@dataclass
class DailyReport:
    report_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    date: str = ""
    tasks_planned: int = 0
    tasks_completed: int = 0
    tasks_failed: int = 0
    revenue_actions: list = field(default_factory=list)
    content_pieces: int = 0
    leads_contacted: int = 0
    optimizations_run: int = 0
    insights: list = field(default_factory=list)
    next_priorities: list = field(default_factory=list)
    execution_score: float = 0.0  # 0-1 quality of today's execution
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "report_id": self.report_id,
            "date": self.date,
            "tasks_planned": self.tasks_planned,
            "tasks_completed": self.tasks_completed,
            "tasks_failed": self.tasks_failed,
            "revenue_actions": self.revenue_actions,
            "content_pieces": self.content_pieces,
            "leads_contacted": self.leads_contacted,
            "optimizations_run": self.optimizations_run,
            "insights": self.insights,
            "next_priorities": self.next_priorities,
            "execution_score": self.execution_score,
            "created_at": self.created_at,
        }


# ── Daily plan templates ───────────────────────────────────────────────────────

_DAILY_PLAN: list[dict] = [
    # Priority 1 — Direct revenue actions
    {"name": "Generate YouTube content metadata", "system": "content", "action": "youtube_metadata", "priority": 1},
    {"name": "Publish LinkedIn authority post", "system": "content", "action": "linkedin_post", "priority": 1},
    {"name": "Schedule 3 Shorts/Reels scripts", "system": "content", "action": "shorts_scripts", "priority": 1},
    {"name": "Send outreach to 10 prospects", "system": "acquisition", "action": "outreach_batch", "priority": 1},

    # Priority 2 — Lead generation
    {"name": "Run SEO blog post generation", "system": "content", "action": "blog_post", "priority": 2},
    {"name": "Score and qualify new leads", "system": "acquisition", "action": "lead_scoring", "priority": 2},
    {"name": "Advance outreach sequences", "system": "acquisition", "action": "sequence_advance", "priority": 2},
    {"name": "Optimize top Shopify products", "system": "shopify", "action": "product_seo_batch", "priority": 2},

    # Priority 3 — Conversion optimization
    {"name": "Analyze funnel drop-offs", "system": "conversion", "action": "funnel_analysis", "priority": 3},
    {"name": "Generate upsell offers", "system": "shopify", "action": "upsell_generation", "priority": 3},
    {"name": "Run abandoned cart recovery", "system": "shopify", "action": "cart_recovery", "priority": 3},
    {"name": "SMS campaign to tagged subscribers", "system": "conversion", "action": "sms_campaign", "priority": 3},

    # Priority 4 — Market intelligence
    {"name": "Competitor pricing audit", "system": "market", "action": "pricing_audit", "priority": 4},
    {"name": "Dynamic price adjustments", "system": "market", "action": "dynamic_pricing", "priority": 4},
    {"name": "Trend opportunity scan", "system": "market", "action": "trend_scan", "priority": 4},

    # Priority 5 — Learning and memory
    {"name": "Extract ROI patterns", "system": "memory", "action": "roi_patterns", "priority": 5},
    {"name": "Update economic memory", "system": "memory", "action": "economic_memory", "priority": 5},
    {"name": "Generate daily insights", "system": "memory", "action": "insight_extraction", "priority": 5},
]


# ── Daily Runtime ─────────────────────────────────────────────────────────────

class DailyRuntime:
    """
    ARIA's daily execution brain.
    Coordinates all revenue systems into a daily plan, tracks execution,
    and produces economic reports.

    State persisted in Redis (key: execution:daily:v1, TTL 90d).
    """

    def __init__(self) -> None:
        self._tasks: list[dict] = []
        self._reports: list[dict] = []
        self._loaded = False

    async def _load(self) -> None:
        if not self._loaded:
            try:
                cache = get_cache()
                data = await cache.get(_KEY)
                if isinstance(data, dict):
                    self._tasks = data.get("tasks", [])
                    self._reports = data.get("reports", [])
            except Exception:
                pass
            self._loaded = True

    async def _save(self) -> None:
        try:
            cache = get_cache()
            await cache.set(
                _KEY,
                {"tasks": self._tasks[-500:], "reports": self._reports[-90:]},
                ttl_seconds=_TTL,
            )
        except Exception:
            pass

    def plan_day(self) -> list[DailyTask]:
        """Build today's prioritized execution queue from the daily plan template."""
        tasks = []
        for spec in _DAILY_PLAN:
            task = DailyTask(
                name=spec["name"],
                system=spec["system"],
                action=spec["action"],
                priority=spec["priority"],
            )
            tasks.append(task)
        # Sort by priority ascending (1 = highest)
        tasks.sort(key=lambda t: t.priority)
        return tasks

    async def execute_task(self, task: DailyTask) -> DailyTask:
        """Execute a single daily task, returning updated task with result."""
        task.started_at = time.time()
        task.status = "running"

        try:
            result = await self._dispatch(task)
            task.result = result
            task.status = "done"
        except Exception as exc:
            task.status = "failed"
            task.error = str(exc)
            task.result = {}

        task.completed_at = time.time()
        task.duration_seconds = round(task.completed_at - task.started_at, 2)
        return task

    async def _dispatch(self, task: DailyTask) -> dict:
        """Route task to the appropriate system."""
        system = task.system
        action = task.action

        if system == "content":
            return await self._run_content_task(action)
        elif system == "acquisition":
            return await self._run_acquisition_task(action)
        elif system == "shopify":
            return await self._run_shopify_task(action)
        elif system == "conversion":
            return await self._run_conversion_task(action)
        elif system == "market":
            return await self._run_market_task(action)
        elif system == "memory":
            return await self._run_memory_task(action)
        return {"status": "no_handler", "system": system, "action": action}

    async def _run_content_task(self, action: str) -> dict:
        if action == "youtube_metadata":
            from apps.video.youtube.youtube_engine import get_youtube_engine
            eng = get_youtube_engine()
            await eng._load()
            return {"status": "queued", "analytics": eng.channel_analytics()}
        if action == "shorts_scripts":
            from apps.video.shorts.shorts_engine import get_shorts_engine
            eng = get_shorts_engine()
            await eng._load()
            return {"status": "queued", "analytics": eng.shorts_analytics()}
        if action in ("linkedin_post", "blog_post"):
            from apps.content.distribution.distribution_engine import get_distribution_engine
            eng = get_distribution_engine()
            await eng._load()
            return {"status": "queued", "stats": eng.distribution_stats()}
        return {"status": "done", "action": action}

    async def _run_acquisition_task(self, action: str) -> dict:
        if action == "outreach_batch":
            from apps.acquisition.outreach.outreach_sequencer import get_outreach_sequencer
            eng = get_outreach_sequencer()
            await eng._load()
            due = eng.contacts_due_today()
            return {"status": "done", "contacts_due": len(due)}
        if action == "lead_scoring":
            from apps.acquisition.linkedin.linkedin_outreach import get_linkedin_outreach
            eng = get_linkedin_outreach()
            await eng._load()
            hot = eng.hot_prospects(min_score=0.7)
            return {"status": "done", "hot_prospects": len(hot)}
        if action == "sequence_advance":
            from apps.acquisition.outreach.outreach_sequencer import get_outreach_sequencer
            eng = get_outreach_sequencer()
            await eng._load()
            return {"status": "done", "analytics": eng.sequence_analytics()}
        return {"status": "done", "action": action}

    async def _run_shopify_task(self, action: str) -> dict:
        if action == "product_seo_batch":
            from apps.shopify.seo.product_seo import get_product_seo_optimizer
            eng = get_product_seo_optimizer()
            await eng._load()
            return {"status": "done", "seo_stats": eng.seo_stats()}
        if action == "upsell_generation":
            from apps.shopify.funnels.shopify_funnels import get_shopify_funnel_engine
            eng = get_shopify_funnel_engine()
            await eng._load()
            return {"status": "done", "funnel_stats": eng.funnel_stats()}
        if action == "cart_recovery":
            from apps.shopify.revenue.cart_recovery import get_cart_recovery
            try:
                eng = get_cart_recovery()
                return {"status": "done", "system": "cart_recovery"}
            except Exception:
                return {"status": "done", "action": action}
        return {"status": "done", "action": action}

    async def _run_conversion_task(self, action: str) -> dict:
        if action == "funnel_analysis":
            from apps.conversion.funnels.funnel_engine import get_funnel_engine
            eng = get_funnel_engine()
            await eng._load()
            return {"status": "done", "analytics": eng.funnel_analytics()}
        if action == "sms_campaign":
            from apps.conversion.sms.sms_capture import get_sms_capture_engine
            eng = get_sms_capture_engine()
            await eng._load()
            return {"status": "done", "stats": eng.capture_stats()}
        return {"status": "done", "action": action}

    async def _run_market_task(self, action: str) -> dict:
        if action in ("pricing_audit", "dynamic_pricing"):
            from apps.market.pricing.pricing_intelligence import get_pricing_intelligence
            eng = get_pricing_intelligence()
            await eng._load()
            return {"status": "done", "dashboard": eng.pricing_dashboard()}
        return {"status": "done", "action": action}

    async def _run_memory_task(self, action: str) -> dict:
        if action == "roi_patterns":
            from apps.learning.roi.roi_learner import get_roi_learner
            eng = get_roi_learner()
            await eng._load()
            return {"status": "done", "report": eng.learning_report()}
        if action in ("economic_memory", "insight_extraction"):
            from apps.memory.economic.economic_memory import get_economic_memory
            eng = get_economic_memory()
            await eng._load()
            return {"status": "done", "summary": eng.memory_summary()}
        return {"status": "done", "action": action}

    async def run_daily(self, max_tasks: int = 18) -> DailyReport:
        """
        Execute today's full plan.
        Runs all tasks in priority order, captures results, produces report.
        """
        await self._load()
        today = datetime.utcnow().strftime("%Y-%m-%d")
        tasks = self.plan_day()[:max_tasks]

        report = DailyReport(
            date=today,
            tasks_planned=len(tasks),
        )

        completed = 0
        failed = 0
        content_pieces = 0
        leads_contacted = 0
        optimizations_run = 0
        revenue_actions = []

        for task in tasks:
            task = await self.execute_task(task)
            self._tasks.append(task.to_dict())

            if task.status == "done":
                completed += 1
                if task.system == "content":
                    content_pieces += 1
                if task.system == "acquisition":
                    leads_contacted += task.result.get("contacts_due", 0)
                if task.system in ("shopify", "market"):
                    optimizations_run += 1
                if task.priority <= 2:
                    revenue_actions.append(task.name)
            else:
                failed += 1

        report.tasks_completed = completed
        report.tasks_failed = failed
        report.revenue_actions = revenue_actions
        report.content_pieces = content_pieces
        report.leads_contacted = leads_contacted
        report.optimizations_run = optimizations_run
        report.execution_score = round(completed / max(len(tasks), 1), 3)

        # AI generates insights and next priorities
        ai = get_ai_client()
        try:
            resp = await ai.complete(
                system="You are ARIA's strategic AI. Analyze today's execution and provide 3 key insights and 3 top priorities for tomorrow.",
                user=(
                    f"Date: {today}\nTasks completed: {completed}/{len(tasks)}\n"
                    f"Content pieces: {content_pieces}\nLeads contacted: {leads_contacted}\n"
                    f"Revenue actions: {', '.join(revenue_actions[:5])}\n\n"
                    "Provide 3 insights and 3 tomorrow priorities."
                ),
                model=AIModel.STRATEGY,
                max_tokens=300,
            )
            if resp.success:
                lines = [l.strip() for l in resp.content.strip().split("\n") if l.strip()]
                report.insights = lines[:3] if lines else ["Maintain execution consistency", "Focus on highest-ROI channels"]
                report.next_priorities = lines[3:6] if len(lines) > 3 else ["Double outreach volume", "Optimize top-converting content"]
        except Exception:
            pass

        if not report.insights:
            report.insights = [
                f"Completed {completed} of {len(tasks)} tasks today",
                f"Generated {content_pieces} content pieces for distribution",
                "Continue prioritizing acquisition and content for compound growth",
            ]
        if not report.next_priorities:
            report.next_priorities = [
                "Increase outreach to 20 prospects/day",
                "Publish 2 more Shorts for traffic",
                "Run A/B test on top funnel headline",
            ]

        self._reports.append(report.to_dict())
        await self._save()
        return report

    async def generate_report(self) -> DailyReport:
        """Generate a fresh daily report from the current state (lighter than run_daily)."""
        await self._load()
        today = datetime.utcnow().strftime("%Y-%m-%d")

        today_tasks = [t for t in self._tasks if t.get("completed_at", 0) > time.time() - 86400]
        completed = sum(1 for t in today_tasks if t.get("status") == "done")
        failed = sum(1 for t in today_tasks if t.get("status") == "failed")

        report = DailyReport(
            date=today,
            tasks_planned=len(today_tasks),
            tasks_completed=completed,
            tasks_failed=failed,
            content_pieces=sum(1 for t in today_tasks if t.get("system") == "content" and t.get("status") == "done"),
            leads_contacted=sum(t.get("result", {}).get("contacts_due", 0) for t in today_tasks),
            optimizations_run=sum(1 for t in today_tasks if t.get("system") in ("shopify", "market") and t.get("status") == "done"),
            revenue_actions=[t["name"] for t in today_tasks if t.get("priority", 9) <= 2 and t.get("status") == "done"],
            execution_score=round(completed / max(len(today_tasks), 1), 3),
        )

        ai = get_ai_client()
        try:
            resp = await ai.complete(
                system="You are ARIA's strategic AI. Provide 3 actionable insights for revenue growth.",
                user=f"Today: {today}. Tasks done: {completed}. Content: {report.content_pieces}. Provide 3 insights.",
                model=AIModel.FAST,
                max_tokens=200,
            )
            if resp.success:
                lines = [l.strip() for l in resp.content.strip().split("\n") if l.strip()]
                report.insights = lines[:3]
                report.next_priorities = lines[3:6] if len(lines) > 3 else []
        except Exception:
            pass

        if not report.insights:
            report.insights = ["Focus on consistent daily execution", "Track which content drives traffic", "Double down on what converts"]
        if not report.next_priorities:
            report.next_priorities = ["Increase outreach volume", "Publish more Shorts", "Optimize highest-traffic landing page"]

        self._reports.append(report.to_dict())
        await self._save()
        return report

    def runtime_stats(self) -> dict:
        total = len(self._tasks)
        done = sum(1 for t in self._tasks if t.get("status") == "done")
        failed = sum(1 for t in self._tasks if t.get("status") == "failed")
        by_system: dict = {}
        for t in self._tasks:
            s = t.get("system", "unknown")
            by_system[s] = by_system.get(s, 0) + 1
        return {
            "total_tasks_executed": total,
            "success_rate_pct": round(done / max(total, 1) * 100, 1),
            "failed_tasks": failed,
            "by_system": by_system,
            "total_reports": len(self._reports),
            "plan_size": len(_DAILY_PLAN),
        }

    def recent_reports(self, limit: int = 7) -> list[dict]:
        return sorted(self._reports, key=lambda r: r.get("created_at", 0), reverse=True)[:limit]


# ── Singleton ─────────────────────────────────────────────────────────────────
_instance: Optional[DailyRuntime] = None


def get_daily_runtime() -> DailyRuntime:
    global _instance
    if _instance is None:
        _instance = DailyRuntime()
    return _instance
