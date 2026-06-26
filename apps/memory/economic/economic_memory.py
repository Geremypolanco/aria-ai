"""EconomicMemory — Stores profitable patterns, failed strategies, and economic insights."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field

from apps.core.memory.redis_client import get_cache
from apps.core.tools.ai_client import AIModel, get_ai_client

_KEY = "memory:economic:v1"
_TTL = 86400 * 365


@dataclass
class EconomicMemory:
    memory_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    memory_type: str = ""
    content: str = ""
    context: dict = field(default_factory=dict)
    impact_usd: float = 0.0
    confidence: float = 0.8
    tags: list = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    times_recalled: int = 0

    def to_dict(self) -> dict:
        return dict(self.__dict__.items())


class EconomicMemoryStore:
    def __init__(self) -> None:
        self._memories: list[dict] = []
        self._loaded = False

    async def _load(self) -> None:
        if not self._loaded:
            try:
                cache = get_cache()
                data = await cache.get(_KEY)
                if isinstance(data, list):
                    self._memories = data
            except Exception:
                pass
            self._loaded = True

    async def _save(self) -> None:
        try:
            cache = get_cache()
            await cache.set(_KEY, self._memories[-500:], ttl_seconds=_TTL)
        except Exception:
            pass

    async def remember(
        self,
        memory_type: str,
        content: str,
        impact_usd: float = 0.0,
        context: dict = None,
        tags: list = None,
    ) -> EconomicMemory:
        if tags is None:
            tags = []
        if context is None:
            context = {}
        await self._load()
        mem = EconomicMemory(
            memory_type=memory_type,
            content=content,
            impact_usd=impact_usd,
            context=context,
            tags=list(tags),
        )
        self._memories.append(mem.to_dict())
        await self._save()
        return mem

    async def recall(
        self, query: str, memory_type: str = "", limit: int = 5
    ) -> list[EconomicMemory]:
        await self._load()
        query_lower = query.lower()
        results = []
        for i, m in enumerate(self._memories):
            if memory_type and m.get("memory_type") != memory_type:
                continue
            content = m.get("content", "").lower()
            tags = [t.lower() for t in m.get("tags", [])]
            if query_lower in content or any(query_lower in t for t in tags):
                self._memories[i]["times_recalled"] = m.get("times_recalled", 0) + 1
                results.append(
                    EconomicMemory(
                        **{k: v for k, v in m.items() if k in EconomicMemory.__dataclass_fields__}
                    )
                )
        await self._save()
        return results[:limit]

    async def extract_insights(self) -> list[dict]:
        await self._load()
        insights = []
        try:
            ai = get_ai_client()
            summary = "; ".join(m.get("content", "")[:100] for m in self._memories[-20:])
            resp = await ai.complete(
                system="Economic pattern analyst.",
                user=f"Extract 3 actionable insights from these economic observations: {summary}",
                model=AIModel.STRATEGY,
                max_tokens=300,
            )
            if resp.success and resp.content:
                for line in resp.content.strip().split("\n"):
                    if line.strip():
                        insights.append(
                            {"insight": line.strip(), "confidence": 0.75, "actionable": True}
                        )
        except Exception:
            pass
        if not insights:
            insights = [
                {"insight": "Focus on highest-ROI channels", "confidence": 0.8, "actionable": True}
            ]
        return insights

    def profitable_patterns(self, min_impact: float = 100.0) -> list[dict]:
        return [m for m in self._memories if m.get("impact_usd", 0) >= min_impact]

    def failed_strategies(self, max_impact: float = -50.0) -> list[dict]:
        return [m for m in self._memories if m.get("impact_usd", 0) <= max_impact]

    def memory_summary(self) -> dict:
        by_type: dict = {}
        for m in self._memories:
            t = m.get("memory_type", "unknown")
            by_type[t] = by_type.get(t, 0) + 1
        net_impact = sum(m.get("impact_usd", 0) for m in self._memories)
        return {
            "total_memories": len(self._memories),
            "by_type": by_type,
            "total_profitable_patterns": len(self.profitable_patterns()),
            "total_failed_strategies": len(self.failed_strategies()),
            "net_impact": round(net_impact, 2),
        }


_instance: EconomicMemoryStore | None = None


def get_economic_memory() -> EconomicMemoryStore:
    global _instance
    if _instance is None:
        _instance = EconomicMemoryStore()
    return _instance
