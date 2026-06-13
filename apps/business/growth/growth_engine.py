"""
Growth Loop Orchestrator — Phase 5
Manages multi-channel growth loops with ROI-driven prioritization.
"""
from __future__ import annotations

import time
import logging
from dataclasses import dataclass, field, asdict
from typing import Any

from apps.core.memory.redis_client import get_cache

logger = logging.getLogger(__name__)

_REDIS_KEY = "growth_engine:v1"
_REDIS_TTL = 86400 * 30  # 30 days


@dataclass
class ChannelMetrics:
    channel: str
    impressions: int
    clicks: int
    conversions: int
    revenue_usd: float
    cac_usd: float
    roi: float
    period_hours: int

    @property
    def ctr(self) -> float:
        if self.impressions == 0:
            return 0.0
        return self.clicks / self.impressions

    @property
    def conversion_rate(self) -> float:
        if self.clicks == 0:
            return 0.0
        return self.conversions / self.clicks


@dataclass
class GrowthLoop:
    loop_id: str
    name: str
    channel: str
    strategy: str
    frequency_hours: float
    priority: int
    enabled: bool
    last_run_ts: float = 0.0
    total_runs: int = 0
    total_revenue_usd: float = 0.0
    success_count: int = 0
    fail_count: int = 0

    @property
    def success_rate(self) -> float:
        total = self.success_count + self.fail_count
        if total == 0:
            return 0.0
        return self.success_count / total

    @property
    def avg_revenue_per_run(self) -> float:
        if self.total_runs == 0:
            return 0.0
        return self.total_revenue_usd / self.total_runs

    def is_due(self) -> bool:
        if not self.enabled:
            return False
        if self.last_run_ts == 0.0:
            return True
        elapsed_hours = (time.time() - self.last_run_ts) / 3600
        return elapsed_hours >= self.frequency_hours


class GrowthEngine:
    """Orchestrates multi-channel growth loops with ROI-driven prioritization."""

    def __init__(self) -> None:
        self._loops: dict[str, GrowthLoop] = {}
        self._loaded = False

    # ------------------------------------------------------------------
    # Persistence helpers
    # ------------------------------------------------------------------

    async def _load(self) -> None:
        if self._loaded:
            return
        try:
            cache = get_cache()
            data = await cache.get(_REDIS_KEY)
            if data and isinstance(data, dict):
                for loop_id, ld in data.items():
                    self._loops[loop_id] = GrowthLoop(**ld)
            else:
                for loop in self._default_loops():
                    self._loops[loop.loop_id] = loop
        except Exception:
            logger.exception("GrowthEngine._load failed — using defaults")
            for loop in self._default_loops():
                self._loops[loop.loop_id] = loop
        self._loaded = True

    async def _save(self) -> None:
        try:
            cache = get_cache()
            payload = {lid: asdict(loop) for lid, loop in self._loops.items()}
            await cache.set(_REDIS_KEY, payload, ttl_seconds=_REDIS_TTL)
        except Exception:
            logger.exception("GrowthEngine._save failed")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def register_loop(self, loop: GrowthLoop) -> None:
        """Register or replace a GrowthLoop (sync, call before async ops)."""
        self._loops[loop.loop_id] = loop

    async def run_due_loops(self) -> list[dict[str, Any]]:
        """Run all loops that are due; returns list of result dicts."""
        await self._load()
        results: list[dict[str, Any]] = []
        due = sorted(
            [lp for lp in self._loops.values() if lp.is_due()],
            key=lambda lp: lp.priority,
            reverse=True,
        )
        for loop in due:
            result = await self.run_loop(loop.loop_id)
            results.append(result)
        return results

    async def run_loop(self, loop_id: str) -> dict[str, Any]:
        """Execute a single growth loop and update its timestamp."""
        await self._load()
        loop = self._loops.get(loop_id)
        if not loop:
            return {"loop_id": loop_id, "success": False, "error": "loop_not_found"}

        revenue = 0.0
        success = False
        error: str | None = None
        try:
            # Simulate execution — real impl would dispatch to channel-specific handlers
            revenue = loop.avg_revenue_per_run if loop.total_runs > 0 else 0.0
            success = True
        except Exception as exc:
            error = str(exc)
            logger.exception("GrowthEngine.run_loop error for %s", loop_id)

        await self.record_result(loop_id, success=success, revenue_usd=revenue, error=error)
        return {
            "loop_id": loop_id,
            "name": loop.name,
            "channel": loop.channel,
            "success": success,
            "revenue_usd": revenue,
            "error": error,
        }

    async def record_result(
        self,
        loop_id: str,
        success: bool,
        revenue_usd: float,
        error: str | None = None,
    ) -> None:
        """Update GrowthLoop statistics after an execution."""
        await self._load()
        loop = self._loops.get(loop_id)
        if not loop:
            return

        loop.last_run_ts = time.time()
        loop.total_runs += 1
        loop.total_revenue_usd += revenue_usd
        if success:
            loop.success_count += 1
        else:
            loop.fail_count += 1
            if error:
                logger.warning("Loop %s failed: %s", loop_id, error)

        await self._save()

    async def optimize_allocation(self) -> dict[str, Any]:
        """Re-prioritize loops by ROI; disable consistently failing loops."""
        await self._load()
        boosted: list[str] = []
        disabled: list[str] = []

        for loop in self._loops.values():
            total_attempts = loop.success_count + loop.fail_count
            if loop.success_rate > 0.6 and loop.avg_revenue_per_run > 1.0:
                loop.priority = min(loop.priority + 1, 10)
                boosted.append(loop.loop_id)
            elif total_attempts >= 5 and loop.success_rate < 0.2:
                loop.enabled = False
                disabled.append(loop.loop_id)

        await self._save()
        return {
            "boosted": boosted,
            "disabled": disabled,
            "active_count": sum(1 for lp in self._loops.values() if lp.enabled),
        }

    async def channel_report(self) -> dict[str, Any]:
        """Returns per-channel aggregated metrics from loop stats."""
        await self._load()
        channels: dict[str, dict[str, Any]] = {}
        for loop in self._loops.values():
            ch = loop.channel
            if ch not in channels:
                channels[ch] = {
                    "channel": ch,
                    "total_runs": 0,
                    "total_revenue_usd": 0.0,
                    "success_count": 0,
                    "fail_count": 0,
                    "loops": 0,
                }
            c = channels[ch]
            c["total_runs"] += loop.total_runs
            c["total_revenue_usd"] += loop.total_revenue_usd
            c["success_count"] += loop.success_count
            c["fail_count"] += loop.fail_count
            c["loops"] += 1

        for c in channels.values():
            total = c["success_count"] + c["fail_count"]
            c["success_rate"] = (c["success_count"] / total) if total > 0 else 0.0
            c["avg_revenue_per_run"] = (
                c["total_revenue_usd"] / c["total_runs"] if c["total_runs"] > 0 else 0.0
            )

        return channels

    def summary(self) -> dict[str, Any]:
        """High-level summary of the growth engine state."""
        active_loops = [lp for lp in self._loops.values() if lp.enabled]
        total_revenue = sum(lp.total_revenue_usd for lp in self._loops.values())

        top_loop: GrowthLoop | None = None
        if active_loops:
            top_loop = max(active_loops, key=lambda lp: lp.avg_revenue_per_run)

        return {
            "total_loops": len(self._loops),
            "active_loops": len(active_loops),
            "top_loop_by_roi": (
                {
                    "loop_id": top_loop.loop_id,
                    "name": top_loop.name,
                    "avg_revenue_per_run": top_loop.avg_revenue_per_run,
                }
                if top_loop
                else None
            ),
            "total_revenue_generated": total_revenue,
        }

    def _default_loops(self) -> list[GrowthLoop]:
        """Default set of 8 growth loops across key channels."""
        return [
            GrowthLoop(
                loop_id="shopify_seo",
                name="Shopify SEO Optimization",
                channel="shopify",
                strategy="keyword_targeting",
                frequency_hours=24,
                priority=8,
                enabled=True,
            ),
            GrowthLoop(
                loop_id="content_marketing",
                name="Content Marketing Engine",
                channel="content",
                strategy="evergreen_blog_publishing",
                frequency_hours=12,
                priority=7,
                enabled=True,
            ),
            GrowthLoop(
                loop_id="social_organic",
                name="Organic Social Distribution",
                channel="social",
                strategy="multi_platform_posting",
                frequency_hours=6,
                priority=6,
                enabled=True,
            ),
            GrowthLoop(
                loop_id="email_nurture",
                name="Email Nurture Sequences",
                channel="email",
                strategy="drip_campaigns",
                frequency_hours=48,
                priority=7,
                enabled=True,
            ),
            GrowthLoop(
                loop_id="affiliate_outreach",
                name="Affiliate Partner Outreach",
                channel="affiliate",
                strategy="partner_recruitment",
                frequency_hours=48,
                priority=5,
                enabled=True,
            ),
            GrowthLoop(
                loop_id="youtube_shorts",
                name="YouTube Shorts Publishing",
                channel="youtube",
                strategy="short_form_video",
                frequency_hours=24,
                priority=6,
                enabled=True,
            ),
            GrowthLoop(
                loop_id="linkedin_content",
                name="LinkedIn Thought Leadership",
                channel="linkedin",
                strategy="b2b_content_posting",
                frequency_hours=24,
                priority=5,
                enabled=True,
            ),
            GrowthLoop(
                loop_id="paid_acquisition",
                name="Paid Acquisition Campaigns",
                channel="paid",
                strategy="performance_ads",
                frequency_hours=12,
                priority=9,
                enabled=True,
            ),
        ]


# ------------------------------------------------------------------
# Singleton factory
# ------------------------------------------------------------------

_growth_engine_instance: GrowthEngine | None = None


def get_growth_engine() -> GrowthEngine:
    global _growth_engine_instance
    if _growth_engine_instance is None:
        _growth_engine_instance = GrowthEngine()
    return _growth_engine_instance
