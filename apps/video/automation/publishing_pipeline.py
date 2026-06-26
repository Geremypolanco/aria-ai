"""
ARIA AI — Publishing Pipeline
Phase 11: Automated video publishing and scheduling.

Capabilities:
  - Job scheduling for video publishing
  - Queue processing with platform stubs
  - Optimal publish time recommendations
  - Pipeline analytics
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field

from apps.core.memory.redis_client import get_cache
from apps.core.tools.ai_client import AIModel, get_ai_client

# ── Redis configuration ────────────────────────────────────────────────────────
_REDIS_KEY = "video:pipeline:v1"
_TTL_90D = 60 * 60 * 24 * 90


# ══════════════════════════════════════════════════════════════════════════════
# Domain object
# ══════════════════════════════════════════════════════════════════════════════


@dataclass
class PublishJob:
    job_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    content_id: str = ""
    platform: str = ""
    title: str = ""
    scheduled_at: float = 0.0
    published_at: float = 0.0
    status: str = "scheduled"
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "job_id": self.job_id,
            "content_id": self.content_id,
            "platform": self.platform,
            "title": self.title,
            "scheduled_at": self.scheduled_at,
            "published_at": self.published_at,
            "status": self.status,
            "metadata": self.metadata,
        }


# ══════════════════════════════════════════════════════════════════════════════
# Publishing Pipeline
# ══════════════════════════════════════════════════════════════════════════════


class PublishingPipeline:
    """
    Automated publishing pipeline for video content.
    State persisted in Redis (key: video:pipeline:v1, TTL 90d).
    """

    def __init__(self):
        self._jobs: list[dict] = []

    # ── Internal helpers ───────────────────────────────────────────────────────

    async def _load(self) -> None:
        cache = get_cache()
        data = await cache.get(_REDIS_KEY)
        if isinstance(data, dict):
            self._jobs = data.get("jobs", [])
        elif isinstance(data, list):
            self._jobs = data

    async def _save(self) -> None:
        cache = get_cache()
        await cache.set(_REDIS_KEY, {"jobs": self._jobs}, ttl_seconds=_TTL_90D)

    def _publish_stub(self, job: PublishJob) -> bool:
        """Graceful platform publishing stub — simulates success."""
        # In production, this would call platform APIs
        return True

    # ── Public methods ─────────────────────────────────────────────────────────

    async def schedule(
        self,
        content_id: str,
        platform: str,
        title: str,
        scheduled_at: float,
        metadata: dict = None,
    ) -> PublishJob:
        """Schedule a video for publishing."""
        if metadata is None:
            metadata = {}
        await self._load()
        job = PublishJob(
            content_id=content_id,
            platform=platform,
            title=title,
            scheduled_at=scheduled_at,
            status="scheduled",
            metadata=dict(metadata),
        )
        self._jobs.append(job.to_dict())
        await self._save()
        return job

    async def process_queue(self) -> list[PublishJob]:
        """Processes due jobs (scheduled_at <= now); marks as 'published'."""
        await self._load()
        now = time.time()
        processed: list[PublishJob] = []

        for job_dict in self._jobs:
            if (
                job_dict.get("status") == "scheduled"
                and job_dict.get("scheduled_at", float("inf")) <= now
            ):
                job = PublishJob(
                    **{k: job_dict[k] for k in PublishJob.__dataclass_fields__ if k in job_dict}
                )
                success = self._publish_stub(job)
                job_dict["status"] = "published" if success else "failed"
                job_dict["published_at"] = now
                job.status = job_dict["status"]
                job.published_at = now
                processed.append(job)

        if processed:
            await self._save()
        return processed

    async def best_publish_times(self, platform: str, niche: str) -> dict:
        """AI recommends optimal posting times."""
        ai = get_ai_client()
        resp = await ai.complete(
            system=(
                "You are a social media timing expert. Recommend the best publish times "
                "for maximum reach and engagement based on platform and niche."
            ),
            user=(
                f"Platform: {platform}\nNiche: {niche}\n\n"
                "Recommend optimal weekdays and times (UTC) for publishing."
            ),
            model=AIModel.FAST,
            max_tokens=300,
        )
        reasoning = resp.content if resp.success else f"Best times for {platform} in {niche}"

        # Platform-specific defaults
        times_map = {
            "youtube": ["14:00", "17:00", "20:00"],
            "tiktok": ["09:00", "12:00", "19:00"],
            "instagram_reels": ["11:00", "14:00", "17:00"],
        }
        return {
            "weekdays": ["Tuesday", "Thursday", "Saturday"],
            "times_utc": times_map.get(platform, ["14:00", "18:00"]),
            "reasoning": reasoning,
        }

    def pipeline_stats(self) -> dict:
        """Return pipeline statistics."""
        scheduled = sum(1 for j in self._jobs if j.get("status") == "scheduled")
        published = sum(1 for j in self._jobs if j.get("status") == "published")
        failed = sum(1 for j in self._jobs if j.get("status") == "failed")
        return {
            "scheduled": scheduled,
            "published": published,
            "failed": failed,
            "total": len(self._jobs),
        }

    def upcoming_publishes(self, limit: int = 10) -> list[dict]:
        """Return upcoming scheduled publishes sorted by scheduled_at."""
        scheduled = [j for j in self._jobs if j.get("status") == "scheduled"]
        return sorted(scheduled, key=lambda j: j.get("scheduled_at", 0))[:limit]


# ── Singleton ──────────────────────────────────────────────────────────────────
_instance: PublishingPipeline | None = None


def get_publishing_pipeline() -> PublishingPipeline:
    global _instance
    if _instance is None:
        _instance = PublishingPipeline()
    return _instance
