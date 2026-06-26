"""
Social media scheduling and publishing platform.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import StrEnum

from apps.core.memory.redis_client import get_cache

_PUBLISHER_KEY = "distribution:social:v1"
_PUBLISHER_TTL = 86400 * 30

_OPTIMAL_HOURS: dict[str, list[int]] = {
    "twitter": [8, 12, 17, 20],
    "instagram": [9, 12, 19, 21],
    "linkedin": [8, 10, 12, 17],
    "tiktok": [7, 12, 19, 21],
    "facebook": [9, 13, 16, 20],
    "youtube": [14, 17, 20],
}


class PublishStatus(StrEnum):
    SCHEDULED = "scheduled"
    PUBLISHED = "published"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class ScheduledPost:
    post_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    platform: str = "twitter"
    content: str = ""
    media_urls: list[str] = field(default_factory=list)
    scheduled_at: float = 0.0
    status: PublishStatus = PublishStatus.SCHEDULED
    published_at: float = 0.0
    error: str = ""
    campaign_id: str = ""
    hashtags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "post_id": self.post_id,
            "platform": self.platform,
            "content": self.content,
            "media_urls": self.media_urls,
            "scheduled_at": self.scheduled_at,
            "status": self.status.value,
            "published_at": self.published_at,
            "error": self.error,
            "campaign_id": self.campaign_id,
            "hashtags": self.hashtags,
        }

    @classmethod
    def from_dict(cls, d: dict) -> ScheduledPost:
        return cls(
            post_id=d.get("post_id", str(uuid.uuid4())),
            platform=d.get("platform", "twitter"),
            content=d.get("content", ""),
            media_urls=d.get("media_urls", []),
            scheduled_at=d.get("scheduled_at", 0.0),
            status=PublishStatus(d.get("status", PublishStatus.SCHEDULED.value)),
            published_at=d.get("published_at", 0.0),
            error=d.get("error", ""),
            campaign_id=d.get("campaign_id", ""),
            hashtags=d.get("hashtags", []),
        )


@dataclass
class PublishingCalendar:
    week_start: str
    posts: list[ScheduledPost] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "week_start": self.week_start,
            "posts": [p.to_dict() for p in self.posts],
            "post_count": len(self.posts),
        }


class SocialPublisher:
    def __init__(self) -> None:
        self._posts: list[dict] = []
        self._loaded = False

    async def _load(self) -> list[dict]:
        if not self._loaded:
            try:
                cache = get_cache()
                data = await cache.get(_PUBLISHER_KEY)
                if isinstance(data, list):
                    self._posts = data
            except Exception:
                pass
            self._loaded = True
        return self._posts

    async def _save(self) -> None:
        try:
            cache = get_cache()
            await cache.set(_PUBLISHER_KEY, self._posts[-2000:], ttl_seconds=_PUBLISHER_TTL)
        except Exception:
            pass

    async def schedule_post(
        self,
        platform: str,
        content: str,
        scheduled_at: float | None = None,
        media_urls: list[str] | None = None,
        hashtags: list[str] | None = None,
        campaign_id: str = "",
    ) -> ScheduledPost:
        await self._load()
        if scheduled_at is None:
            scheduled_at = self._next_optimal_time(platform)

        post = ScheduledPost(
            platform=platform,
            content=content,
            media_urls=media_urls or [],
            scheduled_at=scheduled_at,
            status=PublishStatus.SCHEDULED,
            campaign_id=campaign_id,
            hashtags=hashtags or [],
        )
        self._posts.append(post.to_dict())
        await self._save()
        return post

    def _next_optimal_time(self, platform: str) -> float:
        hours = _OPTIMAL_HOURS.get(platform.lower(), [12, 18])
        now = time.time()
        import datetime

        dt = datetime.datetime.utcfromtimestamp(now)
        for hour in sorted(hours):
            candidate = dt.replace(hour=hour, minute=0, second=0, microsecond=0)
            ts = candidate.timestamp()
            if ts > now + 300:
                return ts
        # Next day first slot
        next_day = dt.replace(hour=hours[0], minute=0, second=0, microsecond=0)
        next_day = next_day + datetime.timedelta(days=1)
        return next_day.timestamp()

    async def publish_due_posts(self) -> list[ScheduledPost]:
        await self._load()
        now = time.time()
        published: list[ScheduledPost] = []

        for i, post_dict in enumerate(self._posts):
            if (
                post_dict["status"] == PublishStatus.SCHEDULED.value
                and post_dict["scheduled_at"] <= now
            ):
                result = await self._publish_post(ScheduledPost.from_dict(post_dict))
                self._posts[i] = result.to_dict()
                published.append(result)

        if published:
            await self._save()
        return published

    async def _publish_post(self, post: ScheduledPost) -> ScheduledPost:
        try:
            # Stub: real platform API calls would go here
            post.status = PublishStatus.PUBLISHED
            post.published_at = time.time()
        except Exception as exc:
            post.status = PublishStatus.FAILED
            post.error = str(exc)
        return post

    def optimal_schedule_times(self, platform: str, days_ahead: int = 7) -> list[float]:
        hours = _OPTIMAL_HOURS.get(platform.lower(), [12, 18])
        import datetime

        now = datetime.datetime.utcnow()
        times: list[float] = []
        for day in range(days_ahead):
            date = now + datetime.timedelta(days=day)
            for hour in hours:
                slot = date.replace(hour=hour, minute=0, second=0, microsecond=0)
                times.append(slot.timestamp())
        return sorted(times)

    async def create_weekly_calendar(
        self,
        content_items: list[dict],
        week_start: str = "",
    ) -> PublishingCalendar:
        import datetime

        if not week_start:
            week_start = datetime.datetime.utcnow().strftime("%Y-%m-%d")

        calendar = PublishingCalendar(week_start=week_start)
        for item in content_items:
            platform = item.get("platform", "twitter")
            post = await self.schedule_post(
                platform=platform,
                content=item.get("body", item.get("title", "")),
                campaign_id=item.get("campaign_id", ""),
                hashtags=item.get("hashtags", []),
            )
            calendar.posts.append(post)
        return calendar

    async def publishing_stats(self) -> dict:
        await self._load()
        by_status: dict[str, int] = {}
        by_platform: dict[str, int] = {}
        for p in self._posts:
            by_status[p["status"]] = by_status.get(p["status"], 0) + 1
            by_platform[p["platform"]] = by_platform.get(p["platform"], 0) + 1
        return {
            "total_posts": len(self._posts),
            "by_status": by_status,
            "by_platform": by_platform,
        }


_publisher_instance: SocialPublisher | None = None


def get_social_publisher() -> SocialPublisher:
    global _publisher_instance
    if _publisher_instance is None:
        _publisher_instance = SocialPublisher()
    return _publisher_instance
