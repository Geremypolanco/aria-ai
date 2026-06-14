"""
MemoryRetriever — Smart semantic retrieval with context injection.
"""
from __future__ import annotations
import time
from typing import Optional
from apps.memory.vector.vector_store import VectorStore, MemoryPoint, get_vector_store
from apps.core.memory.redis_client import get_cache

_RETRIEVER_KEY = "memory:retriever:v1"


class MemoryRetriever:
    def __init__(self):
        self._store = get_vector_store()
        self._session_cache: list[dict] = []

    async def remember(
        self,
        content: str,
        category: str = "general",
        tags: list[str] = [],
        source: str = "",
        score: float = 1.0,
        metadata: dict = {},
    ) -> MemoryPoint:
        """Store a memory point."""
        point = MemoryPoint(
            content=content,
            category=category,
            tags=tags,
            source=source,
            score=score,
            metadata=metadata,
        )
        self._store.upsert(point)
        # Also cache in Redis
        try:
            cache = get_cache()
            recent = await cache.get(_RETRIEVER_KEY) or []
            recent.append(point.to_dict())
            await cache.set(_RETRIEVER_KEY, recent[-500:], ttl_seconds=86400 * 30)
        except Exception:
            pass
        return point

    async def recall(
        self,
        query: str,
        top_k: int = 5,
        category: Optional[str] = None,
    ) -> list[dict]:
        """Retrieve relevant memories for a query."""
        results = self._store.search(query, top_k=top_k, category=category, score_threshold=0.3)
        return [
            {**p.to_dict(), "similarity": round(sim, 4)}
            for p, sim in results
        ]

    async def inject_context(self, task: str, max_tokens: int = 500) -> str:
        """Build context string from relevant memories for a task."""
        memories = await self.recall(task, top_k=5)
        if not memories:
            return ""
        lines = ["Relevant context from memory:"]
        char_count = 0
        for m in memories:
            line = f"- [{m['category']}] {m['content']}"
            char_count += len(line)
            if char_count > max_tokens * 4:
                break
            lines.append(line)
        return "\n".join(lines)

    def status(self) -> dict:
        return {
            "store_status": self._store.status(),
            "session_cache_size": len(self._session_cache),
        }


_retriever_instance: Optional[MemoryRetriever] = None


def get_memory_retriever() -> MemoryRetriever:
    global _retriever_instance
    if _retriever_instance is None:
        _retriever_instance = MemoryRetriever()
    return _retriever_instance
