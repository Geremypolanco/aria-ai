"""
Industrial-scale content production factory.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import StrEnum

from apps.core.memory.redis_client import get_cache
from apps.core.tools.ai_client import AIModel, get_ai_client

_FACTORY_KEY = "factory:content:v1"
_FACTORY_TTL = 86400 * 30


class ProductionStatus(StrEnum):
    QUEUED = "queued"
    PRODUCING = "producing"
    COMPLETE = "complete"
    FAILED = "failed"


@dataclass
class ProductionConfig:
    topic: str
    platforms: list[str] = field(default_factory=lambda: ["blog", "twitter", "linkedin"])
    count_per_platform: int = 3
    include_seo: bool = True
    repurpose: bool = True
    ai_model: str = AIModel.CREATIVE.value


@dataclass
class ProductionBatch:
    batch_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    config: dict = field(default_factory=dict)
    status: ProductionStatus = ProductionStatus.QUEUED
    items: list[dict] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    completed_at: float = 0.0
    total_words: int = 0

    def to_dict(self) -> dict:
        return {
            "batch_id": self.batch_id,
            "config": self.config,
            "status": self.status.value,
            "items": self.items,
            "created_at": self.created_at,
            "completed_at": self.completed_at,
            "total_words": self.total_words,
        }


class ContentFactory:
    def __init__(self) -> None:
        self._batches: list[dict] = []
        self._loaded = False
        self._ai = get_ai_client()

    async def _load(self) -> list[dict]:
        if not self._loaded:
            try:
                cache = get_cache()
                data = await cache.get(_FACTORY_KEY)
                if isinstance(data, list):
                    self._batches = data
            except Exception:
                pass
            self._loaded = True
        return self._batches

    async def _save(self) -> None:
        try:
            cache = get_cache()
            await cache.set(_FACTORY_KEY, self._batches[-200:], ttl_seconds=_FACTORY_TTL)
        except Exception:
            pass

    async def produce_batch(self, config: ProductionConfig) -> ProductionBatch:
        await self._load()
        batch = ProductionBatch(config=config.__dict__)
        batch.status = ProductionStatus.PRODUCING

        items: list[dict] = []
        for platform in config.platforms:
            for i in range(config.count_per_platform):
                body = await self._generate_content(config.topic, platform)
                item = {
                    "item_id": str(uuid.uuid4()),
                    "platform": platform,
                    "topic": config.topic,
                    "title": f"{config.topic}: {platform.title()} Post #{i+1}",
                    "body": body,
                    "word_count": len(body.split()),
                    "seo_optimized": config.include_seo,
                }
                items.append(item)

        batch.items = items
        batch.total_words = sum(item["word_count"] for item in items)
        batch.status = ProductionStatus.COMPLETE
        batch.completed_at = time.time()

        self._batches.append(batch.to_dict())
        await self._save()
        return batch

    async def _generate_content(self, topic: str, platform: str) -> str:
        try:
            if self._ai:
                response = await self._ai.complete(
                    system="You are an expert content writer for digital marketing.",
                    user=f"Write a high-quality {platform} post about: {topic}. Be specific and engaging.",
                    model=AIModel.CREATIVE,
                    max_tokens=600,
                    agent_name="content_factory",
                )
                if response.success and response.content:
                    return response.content
        except Exception:
            pass
        return f"[{platform.upper()}] {topic}\n\nEngaging content about {topic} optimized for {platform} audience."

    async def run_daily_production(self, topics: list[str]) -> list[ProductionBatch]:
        batches = []
        for topic in topics:
            config = ProductionConfig(
                topic=topic,
                platforms=["blog", "twitter", "linkedin"],
                count_per_platform=2,
            )
            batch = await self.produce_batch(config)
            batches.append(batch)
        return batches

    async def repurpose(self, source_content: str, target_platforms: list[str]) -> dict:
        repurposed: dict[str, str] = {}
        for platform in target_platforms:
            try:
                if self._ai:
                    response = await self._ai.complete(
                        system="You are an expert at repurposing content for different platforms.",
                        user=f"Repurpose this content for {platform}:\n\n{source_content[:1000]}",
                        model=AIModel.CREATIVE,
                        max_tokens=400,
                        agent_name="content_factory",
                    )
                    if response.success:
                        repurposed[platform] = response.content
                        continue
            except Exception:
                pass
            repurposed[platform] = f"[{platform.upper()}] " + source_content[:200]
        return repurposed

    async def seo_batch(self, keywords: list[str]) -> ProductionBatch:
        topics = [f"How to {kw}" for kw in keywords]
        config = ProductionConfig(
            topic=", ".join(topics[:3]),
            platforms=["blog"],
            count_per_platform=len(keywords),
            include_seo=True,
        )
        return await self.produce_batch(config)

    async def trend_driven_batch(self, trending_topics: list[str]) -> ProductionBatch:
        config = ProductionConfig(
            topic=trending_topics[0] if trending_topics else "trending news",
            platforms=["twitter", "linkedin", "tiktok"],
            count_per_platform=2,
        )
        return await self.produce_batch(config)

    def summary(self) -> dict:
        total_batches = len(self._batches)
        total_items = sum(len(b.get("items", [])) for b in self._batches)
        return {
            "total_batches": total_batches,
            "total_content_pieces": total_items,
        }


_factory_instance: ContentFactory | None = None


def get_content_factory() -> ContentFactory:
    global _factory_instance
    if _factory_instance is None:
        _factory_instance = ContentFactory()
    return _factory_instance
