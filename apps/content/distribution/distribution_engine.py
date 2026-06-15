"""DistributionEngine — Multi-channel content adaptation and distribution."""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Optional

from apps.core.memory.redis_client import get_cache
from apps.core.tools.ai_client import get_ai_client, AIModel

_KEY = "content:distribution:v1"
_TTL = 86400 * 60


@dataclass
class DistributionJob:
    job_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    content_title: str = ""
    content_type: str = ""
    content_body: str = ""
    channels: list = field(default_factory=list)
    adaptations: dict = field(default_factory=dict)
    scheduled_at: float = 0.0
    status: str = "pending"
    reach_estimate: int = 0
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items()}


class DistributionEngine:
    def __init__(self) -> None:
        self._jobs: list[dict] = []
        self._loaded = False

    async def _load(self) -> None:
        if not self._loaded:
            try:
                cache = get_cache()
                data = await cache.get(_KEY)
                if isinstance(data, list):
                    self._jobs = data
            except Exception:
                pass
            self._loaded = True

    async def _save(self) -> None:
        try:
            cache = get_cache()
            await cache.set(_KEY, self._jobs[-200:], ttl_seconds=_TTL)
        except Exception:
            pass

    async def adapt_for_channel(self, content: str, channel: str, content_type: str) -> str:
        try:
            ai = get_ai_client()
            resp = await ai.complete(
                system="Content adaptation expert.",
                user=f"Adapt this content for {channel}. Type: {content_type}. Content: {content[:500]}. "
                     f"For Twitter: thread of 3 tweets <280 chars each. For LinkedIn: professional post. "
                     f"For Reddit: community-friendly. For Email: newsletter format.",
                model=AIModel.CREATIVE, max_tokens=300,
            )
            if resp.success and resp.content:
                return resp.content.strip()
        except Exception:
            pass
        channel_formats = {
            "twitter": f"🧵 {content[:200]}...\n\nThread 1/{3}",
            "linkedin": f"Sharing insights on {content_type}:\n\n{content[:300]}...",
            "reddit": f"Interesting find on {content_type}:\n\n{content[:400]}...",
            "email": f"Subject: {content_type.title()} Update\n\n{content[:500]}...",
            "medium": content[:600],
        }
        return channel_formats.get(channel, content[:300])

    async def prepare_distribution(self, content_title: str, content_body: str, content_type: str, channels: list) -> DistributionJob:
        await self._load()
        adaptations = {}
        for channel in channels:
            adaptations[channel] = await self.adapt_for_channel(content_body, channel, content_type)
        reach_per_channel = {"twitter": 500, "linkedin": 800, "reddit": 1200, "email": 2000, "medium": 300}
        reach = sum(reach_per_channel.get(c, 200) for c in channels)
        job = DistributionJob(
            content_title=content_title, content_type=content_type,
            content_body=content_body[:1000], channels=channels,
            adaptations=adaptations, reach_estimate=reach,
        )
        self._jobs.append(job.to_dict())
        await self._save()
        return job

    async def schedule_distribution(self, job_id: str, scheduled_at: float) -> bool:
        await self._load()
        for i, j in enumerate(self._jobs):
            if j.get("job_id") == job_id:
                self._jobs[i]["scheduled_at"] = scheduled_at
                self._jobs[i]["status"] = "scheduled"
                await self._save()
                return True
        return False

    async def distribute_now(self, job_id: str) -> dict:
        await self._load()
        for i, j in enumerate(self._jobs):
            if j.get("job_id") == job_id:
                self._jobs[i]["status"] = "distributed"
                await self._save()
                return {"status": "distributed", "channels_reached": j.get("channels", []), "reach_estimate": j.get("reach_estimate", 0)}
        return {"status": "not_found"}

    async def cross_post_strategy(self, niche: str, content_type: str) -> dict:
        try:
            ai = get_ai_client()
            resp = await ai.complete(
                system="Content distribution strategist.",
                user=f"Best channels for {content_type} in {niche}. Return primary_channel, channel_mix %, timing.",
                model=AIModel.STRATEGY, max_tokens=200,
            )
            if resp.success and resp.content:
                return {"primary_channel": "linkedin", "channel_mix": {"linkedin": 0.4, "twitter": 0.3, "email": 0.3}, "best_times": ["9am", "12pm", "5pm"], "reasoning": resp.content[:200]}
        except Exception:
            pass
        return {"primary_channel": "linkedin", "channel_mix": {"linkedin": 0.4, "twitter": 0.3, "email": 0.3}, "best_times": ["9am", "12pm", "5pm"], "reasoning": f"Optimal mix for {niche} {content_type}"}

    def distribution_stats(self) -> dict:
        by_channel: dict = {}
        for j in self._jobs:
            for ch in j.get("channels", []):
                by_channel[ch] = by_channel.get(ch, 0) + 1
        distributed = [j for j in self._jobs if j.get("status") == "distributed"]
        reaches = [j.get("reach_estimate", 0) for j in self._jobs]
        return {
            "total_jobs": len(self._jobs),
            "distributed": len(distributed),
            "pending": len([j for j in self._jobs if j.get("status") == "pending"]),
            "by_channel": by_channel,
            "avg_reach_estimate": round(sum(reaches) / len(reaches)) if reaches else 0,
        }

    def recent_distributions(self, limit: int = 10) -> list[dict]:
        return list(reversed(self._jobs[-limit:]))


_instance: Optional[DistributionEngine] = None


def get_distribution_engine() -> DistributionEngine:
    global _instance
    if _instance is None:
        _instance = DistributionEngine()
    return _instance
