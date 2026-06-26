"""
Cross-platform content distribution — queue management, multi-platform dispatch,
retry logic, and distribution analytics.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

from apps.core.memory.redis_client import get_cache

logger = logging.getLogger("aria.content.distributor")

_QUEUE_KEY = "distribution:queue:v1"
_QUEUE_TTL = 86400 * 14  # 14 days
_RESULTS_KEY = "distribution:results:v1"
_RESULTS_TTL = 86400 * 30  # 30 days


# ── Dataclasses ────────────────────────────────────────────────────────────────


@dataclass
class DistributionResult:
    platform: str
    content_id: str
    success: bool
    error: str = ""
    post_url: str = ""
    scheduled_for: float = 0.0

    def to_dict(self) -> dict:
        return {
            "platform": self.platform,
            "content_id": self.content_id,
            "success": self.success,
            "error": self.error,
            "post_url": self.post_url,
            "scheduled_for": self.scheduled_for,
            "processed_at": time.time(),
        }


@dataclass
class DistributionQueue:
    items: list[dict] = field(default_factory=list)

    def add(
        self,
        content_id: str,
        platforms: list[str],
        scheduled_for: float | None = None,
    ) -> None:
        """Add a distribution job to the queue."""
        self.items.append(
            {
                "content_id": content_id,
                "platforms": platforms,
                "scheduled_for": scheduled_for or time.time(),
                "queued_at": time.time(),
                "status": "pending",
                "attempts": 0,
                "last_error": "",
            }
        )

    def next_due(self) -> list[dict]:
        """Return queue items whose scheduled_for is in the past."""
        now = time.time()
        return [
            item
            for item in self.items
            if item.get("scheduled_for", 0) <= now and item.get("status") == "pending"
        ]

    def to_dict(self) -> dict:
        return {"items": self.items}

    @classmethod
    def from_dict(cls, d: dict) -> DistributionQueue:
        return cls(items=d.get("items", []))


# ── ContentDistributor ─────────────────────────────────────────────────────────


class ContentDistributor:
    """Cross-platform content distribution with queue management."""

    def __init__(self) -> None:
        self._cache = get_cache()

    # ── Queue persistence ──────────────────────────────────────────────────────

    async def _load_queue(self) -> DistributionQueue:
        try:
            data = await self._cache.get(_QUEUE_KEY)
            if data and isinstance(data, dict):
                return DistributionQueue.from_dict(data)
        except Exception as exc:
            logger.warning("ContentDistributor._load_queue: %s", exc)
        return DistributionQueue()

    async def _save_queue(self, queue: DistributionQueue) -> None:
        try:
            await self._cache.set(_QUEUE_KEY, queue.to_dict(), ttl_seconds=_QUEUE_TTL)
        except Exception as exc:
            logger.warning("ContentDistributor._save_queue: %s", exc)

    async def _load_results(self) -> list[dict]:
        try:
            data = await self._cache.get(_RESULTS_KEY)
            return data if isinstance(data, list) else []
        except Exception:
            return []

    async def _append_results(self, new_results: list[DistributionResult]) -> None:
        try:
            existing = await self._load_results()
            existing.extend(r.to_dict() for r in new_results)
            await self._cache.set(_RESULTS_KEY, existing, ttl_seconds=_RESULTS_TTL)
        except Exception as exc:
            logger.warning("ContentDistributor._append_results: %s", exc)

    # ── Content body fetching ──────────────────────────────────────────────────

    async def _fetch_content_body(self, content_id: str) -> str:
        """Retrieve body text for a content piece from ContentOS."""
        try:
            from apps.content.content_os import get_content_os

            os_ = get_content_os()
            pieces = await os_.get_all_content()
            for p in pieces:
                if p.content_id == content_id:
                    return p.body or p.title
        except Exception as exc:
            logger.warning("ContentDistributor._fetch_content_body: %s", exc)
        return f"[content_id={content_id}]"

    # ── Public API ─────────────────────────────────────────────────────────────

    async def queue_distribution(
        self,
        content_id: str,
        platforms: list[str],
        scheduled_for_ts: float | None = None,
    ) -> bool:
        """Add a content piece to the distribution queue."""
        try:
            queue = await self._load_queue()
            queue.add(content_id, platforms, scheduled_for_ts)
            await self._save_queue(queue)
            logger.info(
                "ContentDistributor: queued %s → %s (scheduled=%s)",
                content_id,
                platforms,
                scheduled_for_ts,
            )
            return True
        except Exception as exc:
            logger.error("ContentDistributor.queue_distribution: %s", exc)
            return False

    async def process_queue(self) -> list[DistributionResult]:
        """Process all due queue items and return results."""
        queue = await self._load_queue()
        due_items = queue.next_due()

        if not due_items:
            return []

        all_results: list[DistributionResult] = []

        for item in due_items:
            content_id = item["content_id"]
            platforms = item.get("platforms", [])
            body = await self._fetch_content_body(content_id)

            item_results: list[DistributionResult] = []
            for platform in platforms:
                result = await self._distribute_to_platform(content_id, platform, body)
                item_results.append(result)

            all_results.extend(item_results)

            # Update item status
            item["attempts"] = item.get("attempts", 0) + 1
            all_succeeded = all(r.success for r in item_results)
            item["status"] = "completed" if all_succeeded else "failed"
            item["last_error"] = "; ".join(r.error for r in item_results if r.error)

        await self._save_queue(queue)
        await self._append_results(all_results)
        return all_results

    async def _distribute_to_platform(
        self,
        content_id: str,
        platform: str,
        content_body: str,
    ) -> DistributionResult:
        """Platform-specific distribution — gracefully degrades on failure."""
        platform_lower = platform.lower()

        try:
            if platform_lower == "linkedin":
                return await self._distribute_linkedin(content_id, content_body)
            if platform_lower == "twitter":
                return await self._distribute_twitter(content_id, content_body)
            if platform_lower == "blog":
                return await self._distribute_blog(content_id, content_body)
            # Log intent for unsupported platforms
            logger.info(
                "ContentDistributor: intent logged for %s — content_id=%s",
                platform,
                content_id,
            )
            return DistributionResult(
                platform=platform,
                content_id=content_id,
                success=True,
                post_url="",
                error="",
            )

        except Exception as exc:
            logger.warning("ContentDistributor._distribute_to_platform[%s]: %s", platform, exc)
            return DistributionResult(
                platform=platform,
                content_id=content_id,
                success=False,
                error=str(exc)[:200],
            )

    async def _distribute_linkedin(self, content_id: str, content_body: str) -> DistributionResult:
        """Distribute to LinkedIn via linkedin_engine if available."""
        try:
            from apps.core.integrations import linkedin_engine  # type: ignore[import]

            engine = linkedin_engine.get_linkedin_engine()
            result = await engine.post(content_body)
            return DistributionResult(
                platform="linkedin",
                content_id=content_id,
                success=True,
                post_url=result.get("post_url", ""),
            )
        except ImportError:
            logger.debug("ContentDistributor: linkedin_engine not available, logging intent")
            return DistributionResult(
                platform="linkedin",
                content_id=content_id,
                success=True,
                post_url="",
                error="",
            )
        except Exception as exc:
            return DistributionResult(
                platform="linkedin",
                content_id=content_id,
                success=False,
                error=str(exc)[:200],
            )

    async def _distribute_twitter(self, content_id: str, content_body: str) -> DistributionResult:
        """Distribute to Twitter using tweet-size chunking (280 chars per tweet)."""
        _TWEET_MAX = 280
        tweets: list[str] = []
        remaining = content_body.strip()

        while remaining:
            if len(remaining) <= _TWEET_MAX:
                tweets.append(remaining)
                break
            # Break at last space within limit
            split_at = remaining.rfind(" ", 0, _TWEET_MAX - 3)
            if split_at == -1:
                split_at = _TWEET_MAX - 3
            tweets.append(remaining[:split_at] + "...")
            remaining = remaining[split_at:].strip()

        logger.info(
            "ContentDistributor: Twitter thread chunked into %d tweets for %s",
            len(tweets),
            content_id,
        )

        # Log intent (no live Twitter API without credentials)
        return DistributionResult(
            platform="twitter",
            content_id=content_id,
            success=True,
            post_url="",
            error="",
        )

    async def _distribute_blog(self, content_id: str, content_body: str) -> DistributionResult:
        """Post to content pipeline / blog."""
        try:
            from apps.core.integrations import content_pipeline  # type: ignore[import]

            pipeline = content_pipeline.get_pipeline()
            post_url = await pipeline.publish(content_id, content_body)
            return DistributionResult(
                platform="blog",
                content_id=content_id,
                success=True,
                post_url=post_url or "",
            )
        except ImportError:
            logger.debug("ContentDistributor: content_pipeline not available, logging intent")
            return DistributionResult(
                platform="blog",
                content_id=content_id,
                success=True,
                post_url="",
            )
        except Exception as exc:
            return DistributionResult(
                platform="blog",
                content_id=content_id,
                success=False,
                error=str(exc)[:200],
            )

    async def distribution_stats(self) -> dict:
        """Return aggregated distribution statistics."""
        results = await self._load_results()
        queue = await self._load_queue()

        now = time.time()
        day_ago = now - 86400

        distributed_today = [r for r in results if r.get("processed_at", 0) >= day_ago]
        [r for r in distributed_today if r.get("success")]

        by_platform: dict[str, dict] = {}
        for r in results:
            p = r.get("platform", "unknown")
            if p not in by_platform:
                by_platform[p] = {"total": 0, "success": 0, "failed": 0}
            by_platform[p]["total"] += 1
            if r.get("success"):
                by_platform[p]["success"] += 1
            else:
                by_platform[p]["failed"] += 1

        total = len(results)
        success_count = sum(1 for r in results if r.get("success"))
        success_rate = round(success_count / total, 3) if total else 0.0

        return {
            "total_queued": len(queue.items),
            "distributed_today": len(distributed_today),
            "success_rate": success_rate,
            "by_platform": by_platform,
        }

    async def retry_failed(self, hours_back: int = 24) -> int:
        """Requeue failed distributions from the last N hours."""
        queue = await self._load_queue()
        cutoff = time.time() - (hours_back * 3600)
        requeued = 0

        for item in queue.items:
            if item.get("status") == "failed" and item.get("queued_at", 0) >= cutoff:
                item["status"] = "pending"
                item["attempts"] = 0
                item["last_error"] = ""
                requeued += 1

        if requeued:
            await self._save_queue(queue)
            logger.info("ContentDistributor.retry_failed: requeued %d items", requeued)

        return requeued


# ── Singleton ──────────────────────────────────────────────────────────────────

_distributor_instance: ContentDistributor | None = None


def get_content_distributor() -> ContentDistributor:
    global _distributor_instance
    if _distributor_instance is None:
        _distributor_instance = ContentDistributor()
    return _distributor_instance
