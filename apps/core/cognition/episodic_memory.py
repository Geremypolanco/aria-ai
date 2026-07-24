"""
episodic_memory.py — ARIA AI's persistent episodic memory.

ARIA remembers real events across sessions:
  - Previous conversations (compressed and retrievable)
  - Actions executed and their results
  - Mistakes it made and how it resolved them
  - Preferences it learned from the user

Cross-session: persists in Supabase. Cached in Redis.
Semantic retrieval via embeddings (HF sentence-transformers).
"""

from __future__ import annotations

import json
import logging
import time
from datetime import UTC, datetime

import httpx

from apps.core.config import settings

logger = logging.getLogger("aria.episodic_memory")

HF_EMBED_MODEL = "sentence-transformers/all-MiniLM-L6-v2"


class EpisodicMemory:
    """
    ARIA's real episodic memory.
    Stores, retrieves, and relates events across time.
    """

    def __init__(self) -> None:
        self._episodes: list[dict] = []
        self._hf_token = getattr(settings, "HF_TOKEN", None) or getattr(
            settings, "HF_API_KEY", None
        )
        self._http = httpx.AsyncClient(timeout=15.0)
        self._loaded = False

    # ── STORE EPISODES ──────────────────────────────────────────

    async def store(self, episode_type: str, content: str, metadata: dict = None) -> str:
        """Stores a new episode in memory."""
        episode_id = f"{int(time.time() * 1000)}"
        episode = {
            "id": episode_id,
            "type": episode_type,
            "content": content[:2000],
            "metadata": metadata or {},
            "timestamp": datetime.now(UTC).isoformat(),
            "session": getattr(settings, "APP_VERSION", "unknown"),
        }

        # Generate embedding for semantic retrieval
        try:
            embedding = await self._embed(content[:512])
            if embedding:
                episode["embedding"] = embedding
        except Exception:
            pass

        self._episodes.append(episode)
        if len(self._episodes) > 300:
            self._episodes = self._episodes[-200:]

        # Persist to Supabase
        await self._persist_episode(episode)
        return episode_id

    async def store_conversation(self, user_id: str, user_msg: str, aria_response: str) -> None:
        """Stores a conversation exchange."""
        await self.store(
            "conversation",
            f"User: {user_msg[:500]}\nARIA: {aria_response[:500]}",
            {"user_id": user_id, "turns": 1},
        )

    async def store_action(self, action: str, result: str, success: bool) -> None:
        """Stores an executed action and its result."""
        await self.store(
            "action",
            f"Action: {action[:300]}\nResult: {result[:300]}",
            {"success": success},
        )

    async def store_error(self, error: str, context: str, resolution: str = None) -> None:
        """Stores an error and how it was resolved."""
        await self.store(
            "error",
            f"Error: {error[:300]}\nContext: {context[:200]}\nResolution: {resolution or 'pending'}",
            {"resolved": resolution is not None},
        )

    # ── RETRIEVE EPISODES ───────────────────────────────────────

    async def recall(self, query: str, n: int = 5, episode_type: str = None) -> list[dict]:
        """
        Retrieves the most relevant episodes for a query.
        Uses embedding similarity if available, otherwise keyword search.
        """
        if not self._loaded:
            await self.load()

        candidates = self._episodes
        if episode_type:
            candidates = [e for e in candidates if e.get("type") == episode_type]

        if not candidates:
            return []

        # Semantic search via embeddings
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

        # Fallback: keyword search
        query_lower = query.lower()
        scored = []
        for ep in candidates:
            text = ep.get("content", "").lower()
            score = sum(1 for word in query_lower.split() if word in text and len(word) > 3)
            scored.append((score, ep))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [ep for _, ep in scored[:n] if scored[0][0] > 0]

    async def get_recent(self, n: int = 10, episode_type: str = None) -> list[dict]:
        """Gets the most recent episodes."""
        if not self._loaded:
            await self.load()
        eps = self._episodes
        if episode_type:
            eps = [e for e in eps if e.get("type") == episode_type]
        return eps[-n:]

    async def summarize_session(self) -> str:
        """Generates a summary of the current session to include in context."""
        recent = await self.get_recent(20)
        if not recent:
            return "No recent episodes."

        lines = []
        for ep in recent[-10:]:
            ts = ep.get("timestamp", "")[:16]
            content = ep.get("content", "")[:100]
            lines.append(f"[{ts}] {ep['type']}: {content}")

        summary = "\n".join(lines)
        return summary

    # ── EMBEDDINGS ───────────────────────────────────────────────

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

    # ── PERSISTENCE ──────────────────────────────────────────────

    async def _persist_episode(self, episode: dict) -> None:
        try:
            from apps.core.memory.supabase_client import get_db

            db = get_db()
            if db:
                # create_client() returns a SYNC supabase client — its
                # .execute() is a regular method, not a coroutine. Awaiting
                # it raised TypeError on every call, silently swallowed.
                db.table("aria_episodic_memory").insert(
                    {
                        "episode_id": episode["id"],
                        "episode_type": episode["type"],
                        "content": episode["content"],
                        "metadata": episode.get("metadata", {}),
                        "created_at": episode["timestamp"],
                    }
                ).execute()
        except Exception:
            pass

        try:
            from apps.core.memory.redis_client import get_cache

            cache = get_cache()
            if cache:
                key = f"aria:episode:{episode['id']}"
                # value/ttl_seconds were transposed — the episode content was
                # never actually stored (the cached value was the literal
                # string "604800"), and the malformed ttl broke Redis's EX arg.
                await cache.set(
                    key,
                    json.dumps({k: v for k, v in episode.items() if k != "embedding"}),
                    ttl_seconds=86400 * 7,
                )
        except Exception:
            pass

    async def load(self) -> None:
        """Loads recent episodes from Supabase on startup."""
        try:
            from apps.core.memory.supabase_client import get_db

            db = get_db()
            if db:
                # create_client() returns a SYNC supabase client — its
                # .execute() is a regular method, not a coroutine.
                result = (
                    db.table("aria_episodic_memory")
                    .select("*")
                    .order("created_at", desc=True)
                    .limit(100)
                    .execute()
                )
                if result.data:
                    self._episodes = [
                        {
                            "id": r["episode_id"],
                            "type": r["episode_type"],
                            "content": r["content"],
                            "metadata": r.get("metadata", {}),
                            "timestamp": r["created_at"],
                        }
                        for r in reversed(result.data)
                    ]
                    logger.info(
                        "[EpisodicMemory] %d episodes loaded from Supabase", len(self._episodes)
                    )
        except Exception as exc:
            logger.warning("[EpisodicMemory] Load failed: %s", exc)
        self._loaded = True

    async def close(self) -> None:
        await self._http.aclose()


_memory: EpisodicMemory | None = None


def get_episodic_memory() -> EpisodicMemory:
    global _memory
    if _memory is None:
        _memory = EpisodicMemory()
    return _memory
