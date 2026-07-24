"""
episodic_memory.py — ARIA's persistent, per-user memory across sessions.

This is what lets a returning user pick up where they left off in a DIFFERENT
chat thread, days later — the gap between this and aria_mind.py's own
K_HISTORY (which only remembers within a single chat_id) and K_LEARNED (a
global, not per-user, rule bank). Neither of those carries "what did this
specific person tell me last week" across a new conversation.

Storage: one Redis list per user (``aria:memory:{user_id}``), capped and
TTL'd — the same pattern apps/core/cognition/aria_mind.py already uses for
its own history, and the only path guaranteed to work today. Supabase is a
best-effort secondary write for durability/analytics; its absence (no
migration run yet) must never break the Redis path, which is why every
Supabase call is wrapped and its failure is silently swallowed.

This module used to keep episodes in a plain Python list on the instance.
That's wrong for this deployment: fly.toml autoscales the `web` group across
multiple machines, so any two requests can land on different processes with
no shared memory — an in-process list would silently "forget" whatever the
other machine wrote. Redis (Upstash, shared over REST) is the only thing
here that's actually cross-process.
"""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime

import httpx

from apps.core.config import settings

logger = logging.getLogger("aria.episodic_memory")

HF_EMBED_MODEL = "sentence-transformers/all-MiniLM-L6-v2"

_MAX_EPISODES_PER_USER = 200
_TTL_SECONDS = 86400 * 180  # ~6 months of retained memory


class EpisodicMemory:
    """Per-user episodic memory: stores, recalls, and summarizes past episodes."""

    def __init__(self) -> None:
        self._hf_token = getattr(settings, "HF_TOKEN", None) or getattr(
            settings, "HF_API_KEY", None
        )
        self._http = httpx.AsyncClient(timeout=15.0)

    @staticmethod
    def _key(user_id: str) -> str:
        return f"aria:memory:{user_id}"

    def _cache_client(self):
        try:
            from apps.core.memory.redis_client import get_cache

            return get_cache()
        except Exception:
            return None

    # ── STORE EPISODES ────────────────────────────────────────────

    async def store(
        self, user_id: str, episode_type: str, content: str, metadata: dict | None = None
    ) -> str | None:
        """Store a new episode for this user. No-ops (returns None) without a user_id —
        there is nothing sensible to scope anonymous memory to."""
        if not user_id:
            return None
        episode_id = f"{int(time.time() * 1000)}"
        episode = {
            "id": episode_id,
            "type": episode_type,
            "content": content[:2000],
            "metadata": metadata or {},
            "timestamp": datetime.now(UTC).isoformat(),
        }

        try:
            embedding = await self._embed(content[:512])
            if embedding:
                episode["embedding"] = embedding
        except Exception:
            pass

        cache = self._cache_client()
        if cache:
            key = self._key(user_id)
            episodes = await cache.get(key) or []
            if not isinstance(episodes, list):
                episodes = []
            episodes.append(episode)
            episodes = episodes[-_MAX_EPISODES_PER_USER:]
            await cache.set(key, episodes, ttl_seconds=_TTL_SECONDS)

        await self._persist_episode(user_id, episode)
        return episode_id

    async def store_conversation(self, user_id: str, user_msg: str, aria_response: str) -> None:
        """Store one conversation turn."""
        await self.store(
            user_id,
            "conversation",
            f"User: {user_msg[:500]}\nARIA: {aria_response[:500]}",
            {"turns": 1},
        )

    async def store_action(self, user_id: str, action: str, result: str, success: bool) -> None:
        """Store an executed action and its result."""
        await self.store(
            user_id,
            "action",
            f"Action: {action[:300]}\nResult: {result[:300]}",
            {"success": success},
        )

    async def store_error(
        self, user_id: str, error: str, context: str, resolution: str | None = None
    ) -> None:
        """Store an error and how it was resolved."""
        await self.store(
            user_id,
            "error",
            f"Error: {error[:300]}\nContext: {context[:200]}\nResolution: {resolution or 'pending'}",
            {"resolved": resolution is not None},
        )

    # ── RECALL EPISODES ───────────────────────────────────────────

    async def _load_episodes(self, user_id: str, episode_type: str | None = None) -> list[dict]:
        if not user_id:
            return []
        cache = self._cache_client()
        if not cache:
            return []
        episodes = await cache.get(self._key(user_id)) or []
        if not isinstance(episodes, list):
            return []
        if episode_type:
            episodes = [e for e in episodes if e.get("type") == episode_type]
        return episodes

    async def recall(
        self, user_id: str, query: str, n: int = 5, episode_type: str | None = None
    ) -> list[dict]:
        """Retrieve the episodes most relevant to a query for this user.
        Uses embedding similarity when available, else keyword search."""
        candidates = await self._load_episodes(user_id, episode_type)
        if not candidates:
            return []

        try:
            query_emb = await self._embed(query[:512])
            if query_emb and any(e.get("embedding") for e in candidates):
                scored = []
                for ep in candidates:
                    emb = ep.get("embedding")
                    if emb:
                        score = self._cosine_sim(query_emb, emb)
                        scored.append((score, ep))
                scored.sort(key=lambda x: x[0], reverse=True)
                return [ep for _, ep in scored[:n]]
        except Exception:
            pass

        query_lower = query.lower()
        scored = []
        for ep in candidates:
            text = ep.get("content", "").lower()
            score = sum(1 for word in query_lower.split() if word in text and len(word) > 3)
            scored.append((score, ep))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [ep for score, ep in scored[:n] if score > 0]

    async def get_recent(
        self, user_id: str, n: int = 10, episode_type: str | None = None
    ) -> list[dict]:
        """Get this user's most recent episodes."""
        episodes = await self._load_episodes(user_id, episode_type)
        return episodes[-n:]

    async def summarize_session(self, user_id: str) -> str:
        """A short summary of recent episodes, meant to be folded into the
        system context so ARIA can reference earlier sessions."""
        recent = await self.get_recent(user_id, 20)
        if not recent:
            return ""
        lines = []
        for ep in recent[-10:]:
            ts = ep.get("timestamp", "")[:16]
            content = ep.get("content", "")[:160]
            lines.append(f"[{ts}] {ep['type']}: {content}")
        return "\n".join(lines)

    # ── EMBEDDINGS ────────────────────────────────────────────────

    async def _embed(self, text: str) -> list[float] | None:
        if not self._hf_token:
            return None
        try:
            r = await self._http.post(
                f"https://api-inference.huggingface.co/models/{HF_EMBED_MODEL}",
                headers={"Authorization": f"Bearer {self._hf_token}"},
                json={"inputs": text},
                timeout=8.0,
            )
            if r.status_code == 200:
                data = r.json()
                if isinstance(data, list) and data:
                    return data[0] if isinstance(data[0], list) else data
        except Exception:
            pass
        return None

    @staticmethod
    def _cosine_sim(a: list[float], b: list[float]) -> float:
        if len(a) != len(b):
            return 0.0
        dot = sum(x * y for x, y in zip(a, b, strict=False))
        na = sum(x * x for x in a) ** 0.5
        nb = sum(x * x for x in b) ** 0.5
        if na == 0 or nb == 0:
            return 0.0
        return dot / (na * nb)

    # ── SUPABASE (best-effort secondary durability, never load-bearing) ────

    async def _persist_episode(self, user_id: str, episode: dict) -> None:
        try:
            from apps.core.memory.supabase_client import get_db

            db = get_db()
            if db:
                # supabase-py's client is synchronous — .execute() is a plain call,
                # not a coroutine; awaiting it raises TypeError, which the except
                # below would otherwise swallow silently.
                db.table("aria_episodic_memory").insert(
                    {
                        "episode_id": episode["id"],
                        "user_id": user_id,
                        "episode_type": episode["type"],
                        "content": episode["content"],
                        "metadata": episode.get("metadata", {}),
                        "created_at": episode["timestamp"],
                    }
                ).execute()
        except Exception:
            pass

    async def close(self) -> None:
        await self._http.aclose()


_memory: EpisodicMemory | None = None


def get_episodic_memory() -> EpisodicMemory:
    """Process-wide singleton — safe because all actual state lives in Redis,
    not on this object (see the module docstring)."""
    global _memory
    if _memory is None:
        _memory = EpisodicMemory()
    return _memory
