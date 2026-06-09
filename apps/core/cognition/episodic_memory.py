"""
episodic_memory.py — Memoria episódica persistente de ARIA AI.

ARIA recuerda eventos reales entre sesiones:
  - Conversaciones anteriores (comprimidas y recuperables)
  - Acciones ejecutadas y sus resultados
  - Errores que cometió y cómo los resolvió
  - Preferencias que aprendió del usuario

Cross-session: persiste en Supabase. Cache en Redis.
Recuperación semántica via embeddings (HF sentence-transformers).
"""
from __future__ import annotations
import json
import logging
import time
from datetime import datetime, timezone
from typing import Any, Optional
import httpx
from apps.core.config import settings

logger = logging.getLogger("aria.episodic_memory")

HF_EMBED_MODEL = "sentence-transformers/all-MiniLM-L6-v2"


class EpisodicMemory:
    """
    Memoria episódica real de ARIA.
    Almacena, recupera y relaciona eventos a través del tiempo.
    """

    def __init__(self) -> None:
        self._episodes: list[dict] = []
        self._hf_token = getattr(settings, "HF_TOKEN", None) or getattr(settings, "HF_API_KEY", None)
        self._http = httpx.AsyncClient(timeout=15.0)
        self._loaded = False

    # ── ALMACENAR EPISODIOS ───────────────────────────────────────

    async def store(self, episode_type: str, content: str, metadata: dict = None) -> str:
        """Almacena un nuevo episodio en memoria."""
        episode_id = f"{int(time.time() * 1000)}"
        episode = {
            "id": episode_id,
            "type": episode_type,
            "content": content[:2000],
            "metadata": metadata or {},
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "session": getattr(settings, "APP_VERSION", "unknown"),
        }

        # Generar embedding para recuperación semántica
        try:
            embedding = await self._embed(content[:512])
            if embedding:
                episode["embedding"] = embedding
        except Exception:
            pass

        self._episodes.append(episode)
        if len(self._episodes) > 300:
            self._episodes = self._episodes[-200:]

        # Persistir en Supabase
        await self._persist_episode(episode)
        return episode_id

    async def store_conversation(self, user_id: str, user_msg: str, aria_response: str) -> None:
        """Almacena un intercambio de conversación."""
        await self.store(
            "conversation",
            f"Usuario: {user_msg[:500]}\nARIA: {aria_response[:500]}",
            {"user_id": user_id, "turns": 1},
        )

    async def store_action(self, action: str, result: str, success: bool) -> None:
        """Almacena una acción ejecutada y su resultado."""
        await self.store(
            "action",
            f"Acción: {action[:300]}\nResultado: {result[:300]}",
            {"success": success},
        )

    async def store_error(self, error: str, context: str, resolution: str = None) -> None:
        """Almacena un error y cómo se resolvió."""
        await self.store(
            "error",
            f"Error: {error[:300]}\nContexto: {context[:200]}\nResolución: {resolution or 'pendiente'}",
            {"resolved": resolution is not None},
        )

    # ── RECUPERAR EPISODIOS ───────────────────────────────────────

    async def recall(self, query: str, n: int = 5, episode_type: str = None) -> list[dict]:
        """
        Recupera los episodios más relevantes para una query.
        Usa similitud de embedding si está disponible, sino keyword search.
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
        """Obtiene los episodios más recientes."""
        if not self._loaded:
            await self.load()
        eps = self._episodes
        if episode_type:
            eps = [e for e in eps if e.get("type") == episode_type]
        return eps[-n:]

    async def summarize_session(self) -> str:
        """Genera un resumen de la sesión actual para incluir en el contexto."""
        recent = await self.get_recent(20)
        if not recent:
            return "Sin episodios recientes."

        lines = []
        for ep in recent[-10:]:
            ts = ep.get("timestamp", "")[:16]
            content = ep.get("content", "")[:100]
            lines.append(f"[{ts}] {ep['type']}: {content}")

        summary = "\n".join(lines)
        return summary

    # ── EMBEDDINGS ────────────────────────────────────────────────

    async def _embed(self, text: str) -> Optional[list[float]]:
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
        dot = sum(x * y for x, y in zip(a, b))
        na = sum(x * x for x in a) ** 0.5
        nb = sum(x * x for x in b) ** 0.5
        if na == 0 or nb == 0:
            return 0.0
        return dot / (na * nb)

    # ── PERSISTENCIA ──────────────────────────────────────────────

    async def _persist_episode(self, episode: dict) -> None:
        try:
            from apps.core.memory.supabase_client import get_db
            db = get_db()
            if db:
                await db.table("aria_episodic_memory").insert({
                    "episode_id": episode["id"],
                    "episode_type": episode["type"],
                    "content": episode["content"],
                    "metadata": episode.get("metadata", {}),
                    "created_at": episode["timestamp"],
                }).execute()
        except Exception:
            pass

        try:
            from apps.core.memory.redis_client import get_cache
            cache = get_cache()
            if cache:
                key = f"aria:episode:{episode['id']}"
                await cache.set(key, 86400 * 7, json.dumps({k: v for k, v in episode.items() if k != "embedding"}))
        except Exception:
            pass

    async def load(self) -> None:
        """Carga episodios recientes desde Supabase al iniciar."""
        try:
            from apps.core.memory.supabase_client import get_db
            db = get_db()
            if db:
                result = await db.table("aria_episodic_memory") \
                    .select("*").order("created_at", desc=True).limit(100).execute()
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
                    logger.info("[EpisodicMemory] %d episodios cargados desde Supabase", len(self._episodes))
        except Exception as exc:
            logger.warning("[EpisodicMemory] Load failed: %s", exc)
        self._loaded = True

    async def close(self) -> None:
        await self._http.aclose()


_memory: Optional[EpisodicMemory] = None

def get_episodic_memory() -> EpisodicMemory:
    global _memory
    if _memory is None:
        _memory = EpisodicMemory()
    return _memory
