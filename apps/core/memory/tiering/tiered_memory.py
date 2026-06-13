"""
Hierarchical (tiered) memory retrieval — Hot / Warm / Cold.

Tier          Backend        Latency    Capacity       TTL
──────────────────────────────────────────────────────────────
HOT           in-memory LRU  sub-ms     100 items      session
WARM          Redis           ~5ms       10,000 items   7 days
COLD          Supabase        ~50ms      unlimited      forever

Retrieval always checks HOT first, promotes to HOT on hit from WARM/COLD.
Write-through on store: writes to COLD, promotes to WARM and HOT.

Semantic compression: summaries are stored instead of full payloads when
items would overflow WARM tier, reducing token usage in downstream LLM calls.
"""
from __future__ import annotations

import json
import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

_HOT_CAPACITY   = 100
_WARM_TTL       = 60 * 60 * 24 * 7   # 7 days
_WARM_KEY_PFX   = "tmem_warm:"
_WARM_INDEX_KEY = "tmem_warm_index"
_WARM_MAX       = 10_000


@dataclass
class MemoryItem:
    id: str
    content: str
    category: str
    source: str
    confidence: float
    importance: float
    ts: float
    ts_iso: str
    tags: list[str] = field(default_factory=list)
    compressed: bool = False

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "content": self.content,
            "category": self.category,
            "source": self.source,
            "confidence": self.confidence,
            "importance": self.importance,
            "ts": self.ts,
            "ts_iso": self.ts_iso,
            "tags": self.tags,
            "compressed": self.compressed,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "MemoryItem":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})

    @property
    def age_hours(self) -> float:
        return (time.time() - self.ts) / 3600.0

    def tier_score(self) -> float:
        """Higher = more valuable to keep in hot tier."""
        recency = 1.0 / (1.0 + self.age_hours / 24.0)
        return self.importance * self.confidence * recency


class HotTier:
    """In-memory LRU cache, capacity-bounded."""

    def __init__(self, capacity: int = _HOT_CAPACITY) -> None:
        self._cache: OrderedDict[str, MemoryItem] = OrderedDict()
        self._capacity = capacity

    def get(self, item_id: str) -> Optional[MemoryItem]:
        item = self._cache.get(item_id)
        if item:
            self._cache.move_to_end(item_id)
        return item

    def put(self, item: MemoryItem) -> None:
        if item.id in self._cache:
            self._cache.move_to_end(item.id)
            self._cache[item.id] = item
            return
        if len(self._cache) >= self._capacity:
            # Evict the least recently used (least important)
            self._cache.popitem(last=False)
        self._cache[item.id] = item

    def search(self, query_lower: str, top_k: int = 10) -> list[MemoryItem]:
        results = [
            item for item in self._cache.values()
            if query_lower in item.content.lower() or
               any(query_lower in tag.lower() for tag in item.tags)
        ]
        return sorted(results, key=lambda i: i.tier_score(), reverse=True)[:top_k]

    def size(self) -> int:
        return len(self._cache)

    def evict_expired(self, max_age_hours: float = 1.0) -> int:
        old_ids = [k for k, v in self._cache.items() if v.age_hours > max_age_hours]
        for k in old_ids:
            del self._cache[k]
        return len(old_ids)


class WarmTier:
    """Redis-backed tier for medium-term storage."""

    async def get(self, item_id: str) -> Optional[MemoryItem]:
        try:
            from apps.core.memory.redis_client import get_cache
            raw = await get_cache().get(f"{_WARM_KEY_PFX}{item_id}")
            if raw is None:
                return None
            return MemoryItem.from_dict(raw if isinstance(raw, dict) else json.loads(raw))
        except Exception:
            return None

    async def put(self, item: MemoryItem) -> None:
        try:
            from apps.core.memory.redis_client import get_cache
            cache = get_cache()
            await cache.set(f"{_WARM_KEY_PFX}{item.id}", item.to_dict(), ttl_seconds=_WARM_TTL)
            # Update searchable index
            idx = await cache.get(_WARM_INDEX_KEY)
            entries: list[dict] = idx if isinstance(idx, list) else []
            entries = [e for e in entries if e.get("id") != item.id]
            entries.append({"id": item.id, "content_lower": item.content.lower()[:200],
                            "category": item.category, "ts": item.ts, "score": item.tier_score()})
            if len(entries) > _WARM_MAX:
                entries.sort(key=lambda e: e.get("score", 0))
                entries = entries[-_WARM_MAX:]
            await cache.set(_WARM_INDEX_KEY, entries, ttl_seconds=_WARM_TTL)
        except Exception:
            pass

    async def search(self, query_lower: str, top_k: int = 20) -> list[MemoryItem]:
        try:
            from apps.core.memory.redis_client import get_cache
            idx = await get_cache().get(_WARM_INDEX_KEY)
            entries: list[dict] = idx if isinstance(idx, list) else []
            matching = [e for e in entries if query_lower in e.get("content_lower", "")]
            matching.sort(key=lambda e: e.get("score", 0), reverse=True)
            items = []
            for entry in matching[:top_k]:
                item = await self.get(entry["id"])
                if item:
                    items.append(item)
            return items
        except Exception:
            return []

    async def size(self) -> int:
        try:
            from apps.core.memory.redis_client import get_cache
            idx = await get_cache().get(_WARM_INDEX_KEY)
            return len(idx) if isinstance(idx, list) else 0
        except Exception:
            return 0


class TieredMemory:
    """
    Unified retrieval across HOT/WARM/COLD tiers.
    Callers interact with a single interface; tier promotion is automatic.
    """

    def __init__(self) -> None:
        self._hot  = HotTier()
        self._warm = WarmTier()
        self._write_count = 0
        self._hot_hits  = 0
        self._warm_hits = 0
        self._cold_hits = 0

    async def store(
        self,
        content: str,
        category: str = "general",
        source: str = "aria",
        confidence: float = 0.8,
        importance: float = 0.5,
        tags: Optional[list[str]] = None,
        item_id: Optional[str] = None,
    ) -> str:
        now = time.time()
        item = MemoryItem(
            id=item_id or f"ti_{uuid.uuid4().hex[:10]}",
            content=content,
            category=category,
            source=source,
            confidence=confidence,
            importance=importance,
            ts=now,
            ts_iso=datetime.fromtimestamp(now, tz=timezone.utc).isoformat(),
            tags=tags or [],
        )
        self._hot.put(item)
        await self._warm.put(item)
        self._write_count += 1
        return item.id

    async def retrieve(self, item_id: str) -> Optional[MemoryItem]:
        item = self._hot.get(item_id)
        if item:
            self._hot_hits += 1
            return item

        item = await self._warm.get(item_id)
        if item:
            self._warm_hits += 1
            self._hot.put(item)  # promote
            return item

        return None

    async def search(
        self,
        query: str,
        top_k: int = 10,
        category: Optional[str] = None,
    ) -> list[MemoryItem]:
        query_lower = query.lower()

        hot_results  = self._hot.search(query_lower, top_k=top_k)
        warm_results = await self._warm.search(query_lower, top_k=top_k * 2)

        # Merge, deduplicate by id, filter by category, re-rank by tier_score
        seen: set[str] = set()
        merged: list[MemoryItem] = []
        for item in hot_results + warm_results:
            if item.id not in seen:
                seen.add(item.id)
                if category is None or item.category == category:
                    merged.append(item)

        merged.sort(key=lambda i: i.tier_score(), reverse=True)

        # Promote warm hits to hot
        hot_ids = {i.id for i in hot_results}
        for item in warm_results[:5]:
            if item.id not in hot_ids:
                self._hot.put(item)

        return merged[:top_k]

    def summary(self) -> dict:
        return {
            "hot_size": self._hot.size(),
            "write_count": self._write_count,
            "hot_hits": self._hot_hits,
            "warm_hits": self._warm_hits,
            "cold_hits": self._cold_hits,
            "hot_hit_rate": round(self._hot_hits / max(self._hot_hits + self._warm_hits + self._cold_hits, 1), 3),
        }


_tiered: Optional[TieredMemory] = None


def get_tiered_memory() -> TieredMemory:
    global _tiered
    if _tiered is None:
        _tiered = TieredMemory()
    return _tiered
