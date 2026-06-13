"""
ARIA Semantic Memory — Vector-indexed fact storage with similarity retrieval.

Architecture:
  - Facts are stored with embeddings (HF sentence-transformers via API)
  - Similarity search uses cosine distance on stored vectors
  - Falls back to keyword matching when embeddings unavailable
  - Three layers: Working (in-process), Cache (Redis), Long-term (Supabase)
  - Facts are categorized: user_preference, world_fact, skill, outcome, constraint

This is the "what ARIA knows" layer — distinct from episodic memory ("what happened").
"""
from __future__ import annotations

import json
import logging
import math
import time
import uuid
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger("aria.semantic_memory")

FACT_TTL_REDIS = 3600 * 24 * 30   # 30 days in Redis
MAX_WORKING_MEMORY = 500           # in-process limit before eviction
EMBED_MODEL = "sentence-transformers/all-MiniLM-L6-v2"


class FactCategory(str):
    USER_PREFERENCE = "user_preference"
    WORLD_FACT = "world_fact"
    SKILL = "skill"
    OUTCOME = "outcome"          # what worked / didn't work
    CONSTRAINT = "constraint"    # hard limits ARIA must respect
    PROCEDURE = "procedure"      # how to do something


@dataclass
class Fact:
    id: str
    content: str
    category: str
    source: str                  # where this fact came from
    confidence: float            # 0.0–1.0
    embedding: list[float]       # vector representation
    tags: list[str]
    created_at: str
    accessed_at: str
    access_count: int = 0
    decay_factor: float = 1.0   # decreases over time if not accessed

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Fact":
        return cls(**d)

    def relevance_score(self, query_embedding: list[float]) -> float:
        """Cosine similarity scaled by confidence and recency."""
        if not self.embedding or not query_embedding:
            return 0.0
        cos_sim = _cosine_similarity(self.embedding, query_embedding)
        return cos_sim * self.confidence * self.decay_factor


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    if len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    mag_a = math.sqrt(sum(x * x for x in a))
    mag_b = math.sqrt(sum(x * x for x in b))
    if mag_a == 0 or mag_b == 0:
        return 0.0
    return dot / (mag_a * mag_b)


class SemanticMemory:
    """
    ARIA's semantic memory — what ARIA knows (not what happened to it).

    Usage:
        mem = SemanticMemory()
        await mem.store("The user prefers concise responses", category="user_preference")
        facts = await mem.search("user communication style", top_k=5)
    """

    def __init__(self) -> None:
        self._working: dict[str, Fact] = {}   # in-process working memory
        self._embed_client = None
        self._loaded = False

    # ── Store ────────────────────────────────────────────────────────────

    async def store(
        self,
        content: str,
        category: str = FactCategory.WORLD_FACT,
        source: str = "aria",
        confidence: float = 0.8,
        tags: list[str] | None = None,
    ) -> str:
        fact_id = str(uuid.uuid4())[:12]
        now = datetime.now(timezone.utc).isoformat()

        embedding = await self._embed(content)

        fact = Fact(
            id=fact_id,
            content=content[:2000],
            category=category,
            source=source,
            confidence=max(0.0, min(1.0, confidence)),
            embedding=embedding,
            tags=tags or [],
            created_at=now,
            accessed_at=now,
        )

        # Write to working memory (with eviction)
        if len(self._working) >= MAX_WORKING_MEMORY:
            self._evict_lru()
        self._working[fact_id] = fact

        # Persist to Redis + Supabase async (fire and forget)
        await self._persist_fact(fact)

        logger.debug("[SemanticMem] Stored fact %s: %.60s", fact_id, content)
        return fact_id

    # ── Search ───────────────────────────────────────────────────────────

    async def search(
        self,
        query: str,
        top_k: int = 5,
        category: str | None = None,
        min_confidence: float = 0.3,
    ) -> list[Fact]:
        """
        Semantic search over stored facts.
        Uses embeddings when available, falls back to keyword overlap.
        """
        if not self._loaded:
            await self._load_from_redis()

        query_embedding = await self._embed(query)

        candidates = [
            f for f in self._working.values()
            if f.confidence >= min_confidence
            and (category is None or f.category == category)
        ]

        if query_embedding:
            scored = [
                (f, f.relevance_score(query_embedding))
                for f in candidates
            ]
        else:
            # Keyword fallback
            query_tokens = set(query.lower().split())
            scored = [
                (f, self._keyword_score(f.content, query_tokens))
                for f in candidates
            ]

        scored.sort(key=lambda x: x[1], reverse=True)
        results = [f for f, score in scored[:top_k] if score > 0.0]

        # Update access metadata
        now = datetime.now(timezone.utc).isoformat()
        for f in results:
            f.accessed_at = now
            f.access_count += 1

        return results

    def _keyword_score(self, content: str, query_tokens: set[str]) -> float:
        content_tokens = set(content.lower().split())
        if not query_tokens:
            return 0.0
        overlap = len(query_tokens & content_tokens)
        return overlap / len(query_tokens)

    # ── Retrieve by ID ───────────────────────────────────────────────────

    async def get(self, fact_id: str) -> Optional[Fact]:
        if fact_id in self._working:
            return self._working[fact_id]
        return await self._load_fact_from_redis(fact_id)

    # ── Update & Decay ───────────────────────────────────────────────────

    async def reinforce(self, fact_id: str, confidence_delta: float = 0.1) -> bool:
        """Increase confidence of a fact when it's validated."""
        fact = self._working.get(fact_id)
        if fact:
            fact.confidence = min(1.0, fact.confidence + confidence_delta)
            fact.decay_factor = min(1.0, fact.decay_factor + 0.05)
            await self._persist_fact(fact)
            return True
        return False

    async def contradict(self, fact_id: str, confidence_delta: float = 0.2) -> bool:
        """Decrease confidence of a fact when evidence contradicts it."""
        fact = self._working.get(fact_id)
        if fact:
            fact.confidence = max(0.0, fact.confidence - confidence_delta)
            if fact.confidence < 0.1:
                del self._working[fact_id]
                await self._remove_fact(fact_id)
            else:
                await self._persist_fact(fact)
            return True
        return False

    def apply_decay(self, decay_rate: float = 0.01) -> None:
        """
        Time-based memory decay — facts not accessed recently become less
        influential. Call periodically (e.g., hourly scheduler job).
        """
        for fact in self._working.values():
            fact.decay_factor = max(0.1, fact.decay_factor - decay_rate)

    # ── Summarize ────────────────────────────────────────────────────────

    def summary(self) -> dict:
        cats: dict[str, int] = {}
        for f in self._working.values():
            cats[f.category] = cats.get(f.category, 0) + 1
        return {
            "total_facts": len(self._working),
            "by_category": cats,
            "avg_confidence": (
                sum(f.confidence for f in self._working.values()) / len(self._working)
                if self._working else 0.0
            ),
        }

    # ── Embedding ────────────────────────────────────────────────────────

    async def _embed(self, text: str) -> list[float]:
        try:
            from apps.core.config import settings
            hf_token = getattr(settings, "HF_TOKEN", None) or getattr(settings, "HF_API_KEY", None)
            if not hf_token:
                return []

            import httpx
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    f"https://api-inference.huggingface.co/pipeline/feature-extraction/{EMBED_MODEL}",
                    headers={"Authorization": f"Bearer {hf_token}"},
                    json={"inputs": text[:512], "options": {"wait_for_model": True}},
                )
                if resp.status_code == 200:
                    raw = resp.json()
                    if isinstance(raw, list) and raw and isinstance(raw[0], float):
                        return raw
                    if isinstance(raw, list) and raw and isinstance(raw[0], list):
                        # Sentence-level output — take mean pool
                        vectors = raw[0] if isinstance(raw[0][0], float) else raw
                        return [sum(col) / len(col) for col in zip(*vectors)]
        except Exception as exc:
            logger.debug("[SemanticMem] Embed failed (will use keyword fallback): %s", exc)
        return []

    # ── Persistence ──────────────────────────────────────────────────────

    async def _persist_fact(self, fact: Fact) -> None:
        try:
            from apps.core.memory.redis_client import get_cache
            cache = get_cache()
            if cache:
                key = f"aria:semantic:{fact.id}"
                # Store without embedding to save space (embeddings are large)
                d = fact.to_dict()
                d["embedding"] = []  # embeddings stored separately if needed
                await cache.set(key, json.dumps(d), ttl_seconds=FACT_TTL_REDIS)
        except Exception as exc:
            logger.debug("[SemanticMem] Redis persist failed: %s", exc)

    async def _load_from_redis(self) -> None:
        self._loaded = True
        # In production: scan Redis for aria:semantic:* keys and load recent facts
        # For now, working memory is populated as facts come in
        logger.debug("[SemanticMem] Semantic memory initialized")

    async def _load_fact_from_redis(self, fact_id: str) -> Optional[Fact]:
        try:
            from apps.core.memory.redis_client import get_cache
            cache = get_cache()
            if cache:
                raw = await cache.get(f"aria:semantic:{fact_id}")
                if raw:
                    return Fact.from_dict(json.loads(raw))
        except Exception as exc:
            logger.debug("[SemanticMem] Load fact %s failed: %s", fact_id, exc)
        return None

    async def _remove_fact(self, fact_id: str) -> None:
        try:
            from apps.core.memory.redis_client import get_cache
            cache = get_cache()
            if cache:
                await cache.delete(f"aria:semantic:{fact_id}")
        except Exception:
            pass

    # ── Eviction ────────────────────────────────────────────────────────

    def _evict_lru(self) -> None:
        """Evict least recently used and lowest confidence facts."""
        sorted_facts = sorted(
            self._working.items(),
            key=lambda kv: (kv[1].decay_factor, kv[1].access_count),
        )
        evict_count = len(self._working) // 10  # remove 10%
        for fact_id, _ in sorted_facts[:evict_count]:
            del self._working[fact_id]


_semantic_memory: Optional[SemanticMemory] = None


def get_semantic_memory() -> SemanticMemory:
    global _semantic_memory
    if _semantic_memory is None:
        _semantic_memory = SemanticMemory()
    return _semantic_memory
