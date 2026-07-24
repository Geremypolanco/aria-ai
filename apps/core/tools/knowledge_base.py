"""
knowledge_base.py — RAG (Retrieval Augmented Generation) for ARIA AI.

Inspired by Dify: ingests documents/URLs, chunks them, embeds them with sentence-transformers,
and enables semantic search to enrich ARIA's context.

ARIA can "learn" from any document, webpage, or text and use it in future responses.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import httpx

logger = logging.getLogger("aria.knowledge_base")

CHUNK_SIZE = 400  # words per chunk
CHUNK_OVERLAP = 40  # overlap words between consecutive chunks
MIN_CHUNK_WORDS = 15  # discard tiny chunks
HF_EMBED_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
SIMILARITY_THRESHOLD = 0.20


@dataclass
class KnowledgeChunk:
    id: str
    source: str
    category: str
    text: str
    embedding: list[float]
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def cosine_similarity(self, other: list[float]) -> float:
        if not self.embedding or not other:
            return 0.0
        if len(self.embedding) != len(other):
            # Mixed embedding sources (e.g. the 384-dim HF model vs. the
            # 128-dim offline _hash_embed fallback) produce vectors that
            # aren't comparable — zip(strict=False) would silently truncate
            # the dot product to the shorter length while the norms below
            # still use each vector's full length, yielding a meaningless,
            # systematically deflated score instead of an explicit "no match".
            return 0.0
        dot = sum(a * b for a, b in zip(self.embedding, other, strict=False))
        norm1 = sum(a**2 for a in self.embedding) ** 0.5
        norm2 = sum(b**2 for b in other) ** 0.5
        return dot / (norm1 * norm2) if norm1 and norm2 else 0.0


class KnowledgeBase:
    """
    Semantic knowledge base for ARIA.
    Persists to Redis; falls back to in-memory storage if Redis is unavailable.
    """

    def __init__(self) -> None:
        self._chunks: dict[str, KnowledgeChunk] = {}
        self._http = httpx.AsyncClient(timeout=30.0)
        self._loaded = False

    # ── INGESTION ─────────────────────────────────────────────────────────────

    async def ingest_text(
        self, text: str, source: str = "manual", category: str = "general"
    ) -> dict[str, Any]:
        """Ingests plain text, chunked, into the knowledge base."""
        await self._ensure_loaded()
        chunks = self._split_text(text)
        added = 0
        for chunk_text in chunks:
            cid = hashlib.md5(f"{source}:{chunk_text[:80]}".encode()).hexdigest()[:12]
            if cid in self._chunks:
                continue
            emb = await self._embed(chunk_text)
            self._chunks[cid] = KnowledgeChunk(
                id=cid, source=source, category=category, text=chunk_text, embedding=emb
            )
            added += 1
        await self._persist()
        logger.info("[KB] +%d chunks from '%s' (total=%d)", added, source, len(self._chunks))
        return {
            "success": True,
            "chunks_added": added,
            "source": source,
            "total_chunks": len(self._chunks),
        }

    async def ingest_url(self, url: str, category: str = "web") -> dict[str, Any]:
        """Downloads and processes a URL."""
        await self._ensure_loaded()
        try:
            from apps.core.tools.web_tools import _assert_public_url

            # Re-validated on every hop (redirects disabled here on purpose) —
            # a URL that resolves to something public can still redirect to an
            # internal address, which would silently bypass a check that only
            # ran once against the original URL.
            next_url = url
            resp = None
            for _hop in range(5):
                await _assert_public_url(next_url)
                resp = await self._http.get(next_url, timeout=20, follow_redirects=False)
                if resp.is_redirect:
                    next_url = str(resp.next_request.url)
                    continue
                break
            else:
                return {"success": False, "error": "too many redirects"}
            resp.raise_for_status()
            text = self._html_to_text(resp.text)
            return await self.ingest_text(text, source=url, category=category)
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    # ── SEARCH ────────────────────────────────────────────────────────────────

    async def search(self, query: str, top_k: int = 5, category: str = "") -> list[dict]:
        """Semantic search. Returns the top_k most relevant chunks."""
        await self._ensure_loaded()
        if not self._chunks:
            return []
        q_emb = await self._embed(query)
        pool = list(self._chunks.values())
        if category:
            pool = [c for c in pool if c.category == category]
        scored = sorted(
            [(c, c.cosine_similarity(q_emb)) for c in pool], key=lambda x: x[1], reverse=True
        )
        return [
            {
                "text": c.text,
                "source": c.source,
                "category": c.category,
                "score": round(s, 4),
                "id": c.id,
            }
            for c, s in scored[:top_k]
            if s >= SIMILARITY_THRESHOLD
        ]

    async def search_formatted(self, query: str, top_k: int = 4) -> str:
        """Returns formatted context string ready to inject into prompts."""
        results = await self.search(query, top_k=top_k)
        if not results:
            return ""
        lines = [f"[KNOWLEDGE BASE — {len(results)} relevant fragments]"]
        for i, r in enumerate(results, 1):
            lines.append(f"\n{i}. Source: {r['source']} (score={r['score']})")
            lines.append(r["text"][:500])
        return "\n".join(lines)

    # ── MANAGEMENT ────────────────────────────────────────────────────────────

    def list_sources(self) -> list[dict]:
        seen: dict[str, dict] = {}
        for c in self._chunks.values():
            if c.source not in seen:
                seen[c.source] = {
                    "source": c.source,
                    "category": c.category,
                    "chunks": 0,
                    "added_at": c.created_at,
                }
            seen[c.source]["chunks"] += 1
        return sorted(seen.values(), key=lambda x: x["added_at"], reverse=True)

    def delete_source(self, source: str) -> int:
        ids = [k for k, v in self._chunks.items() if v.source == source]
        for k in ids:
            del self._chunks[k]
        return len(ids)

    def stats(self) -> dict:
        cats: dict[str, int] = {}
        for c in self._chunks.values():
            cats[c.category] = cats.get(c.category, 0) + 1
        return {"total_chunks": len(self._chunks), "by_category": cats}

    # ── PRIVATE ───────────────────────────────────────────────────────────────

    def _split_text(self, text: str) -> list[str]:
        words = text.split()
        chunks, i = [], 0
        while i < len(words):
            chunk = " ".join(words[i : i + CHUNK_SIZE])
            if len(chunk.split()) >= MIN_CHUNK_WORDS:
                chunks.append(chunk)
            i += CHUNK_SIZE - CHUNK_OVERLAP
        return chunks

    async def _embed(self, text: str) -> list[float]:
        from apps.core.config import settings

        if settings.hf_key:
            try:
                resp = await self._http.post(
                    f"https://api-inference.huggingface.co/pipeline/feature-extraction/{HF_EMBED_MODEL}",
                    headers={"Authorization": f"Bearer {settings.hf_key}"},
                    json={"inputs": text[:512], "options": {"wait_for_model": True}},
                    timeout=15,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    # API returns [[...]] for single input
                    vec = data[0] if isinstance(data, list) and isinstance(data[0], list) else data
                    if isinstance(vec, list) and vec and isinstance(vec[0], (int, float)):
                        return [float(v) for v in vec]
            except Exception as exc:
                logger.debug("[KB] HF embed failed: %s", exc)
        return self._hash_embed(text)

    def _hash_embed(self, text: str) -> list[float]:
        """Deterministic 128-dim pseudo-embedding as offline fallback."""
        dims = 128
        vec = [0.0] * dims
        for w in text.lower().split():
            h = int(hashlib.md5(w.encode()).hexdigest(), 16)
            vec[h % dims] += 1.0
        norm = (sum(v**2 for v in vec) ** 0.5) or 1.0
        return [v / norm for v in vec]

    def _html_to_text(self, html: str) -> str:
        html = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.DOTALL | re.I)
        html = re.sub(r"<[^>]+>", " ", html)
        html = (
            html.replace("&amp;", "&")
            .replace("&lt;", "<")
            .replace("&gt;", ">")
            .replace("&nbsp;", " ")
        )
        return re.sub(r"\s+", " ", html).strip()[:60000]

    async def _persist(self) -> None:
        try:
            from apps.core.memory.redis_client import get_cache

            payload = json.dumps(
                {
                    k: {
                        "source": v.source,
                        "category": v.category,
                        "text": v.text,
                        "embedding": v.embedding,
                        "created_at": v.created_at,
                    }
                    for k, v in self._chunks.items()
                }
            )
            await get_cache().set("aria:knowledge_base", payload, ttl_seconds=86400 * 30)
        except Exception:
            pass

    async def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        try:
            from apps.core.memory.redis_client import get_cache

            raw = await get_cache().get("aria:knowledge_base")
            if raw:
                data = json.loads(raw) if isinstance(raw, str) else raw
                for k, v in data.items():
                    self._chunks[k] = KnowledgeChunk(
                        id=k,
                        source=v["source"],
                        category=v["category"],
                        text=v["text"],
                        embedding=v["embedding"],
                        created_at=v.get("created_at", ""),
                    )
                logger.info("[KB] Loaded %d chunks from Redis", len(self._chunks))
        except Exception:
            pass


_kb: KnowledgeBase | None = None


def get_knowledge_base() -> KnowledgeBase:
    global _kb
    if _kb is None:
        _kb = KnowledgeBase()
    return _kb
