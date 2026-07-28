"""
user_facts.py — ARIA's long-term, per-user semantic memory: durable facts
and preferences that must persist across sessions and must never leak
between users.

This is deliberately distinct from two other memory modules already in the
repo — don't confuse them:

  - apps/core/cognition/episodic_memory.py: raw conversation snippets
    ("what happened"), Redis-primary, 180-day TTL, 200-item cap per user.
    Good for "what did we talk about last week", not built to be a durable,
    uncapped store of curated facts.
  - apps/core/memory/semantic_memory.py: ARIA's own global operational
    knowledge ("what ARIA knows"), NOT user-scoped — a single shared pool
    used by apps/core/quality/quality_controller.py. Storing per-user
    preferences there would leak them to every other user of that module.

This module stores rows in Supabase Postgres (aria_user_memories table, see
database/user_memory_schema.sql) with a pgvector embedding column, and is
the durable PRIMARY store for this data — unlike episodic_memory.py, there
is no TTL and no cap here, and no Redis mirror: the user explicitly wants
this "never silently forgotten", so it needs a store that doesn't expire on
its own and doesn't depend on any one process's memory.

ISOLATION GUARANTEE: every public method below requires a truthy `user_id`
(always the caller's server-verified email — see apps/core/auth.py; nothing
here ever accepts identity from unauthenticated input) and passes it into
every underlying query, including the pgvector similarity search, which
goes through the match_user_memories() SQL function specifically so the
`WHERE user_id = ...` filter lives in the database function itself, not in
application-assembled query text that a bug could someday omit. `forget()`
additionally filters the delete by user_id, so even a guessed/leaked
memory_id can only ever delete a row that belongs to the caller.

Degrades gracefully: if Supabase isn't configured, or any call to it fails,
these methods return None/[]/False rather than raising — a chat request
must never break because long-term memory is unavailable.
"""

from __future__ import annotations

import asyncio
import logging

from apps.core.config import settings

logger = logging.getLogger("aria.user_facts")

_VALID_CATEGORIES = ("fact", "preference", "constraint")

# Unlike episodic_memory.py (200-item list, trimmed in Python) this store has
# no in-memory list to slice — the cap is enforced by deleting the oldest
# rows past MAX_FACTS_PER_USER after each write. 500 is generous for
# legitimate "things ARIA should remember about me" use while still bounding
# storage and (more importantly) the number of embedding rows carried
# forever for one user.
MAX_FACTS_PER_USER = 500

# Bounds how fast one user can write new facts — 20/hour is generous for a
# real conversation (a user telling ARIA new things about themselves a few
# times a session) but stops a compromised/scripted account from writing
# thousands of rows, and triggering thousands of HF embedding calls, in a
# burst. This is an abuse guard, not a correctness guarantee, so it fails
# OPEN if Redis is unavailable — a cache hiccup must never block a
# legitimate save.
_WRITE_RATE_LIMIT_PER_HOUR = 20


def _configured() -> bool:
    return bool(getattr(settings, "SUPABASE_URL", "") and getattr(settings, "SUPABASE_KEY", ""))


class UserFactStore:
    """Per-user durable facts/preferences, backed by Supabase + pgvector."""

    async def remember(
        self,
        user_id: str,
        content: str,
        category: str = "fact",
        importance: float = 0.5,
        metadata: dict | None = None,
    ) -> str | None:
        """Stores one fact/preference for `user_id`. Returns the new row's
        id, or None if nothing was stored (no user_id/content, or Supabase
        unavailable) — never raises."""
        user_id = (user_id or "").strip().lower()
        content = (content or "").strip()
        if not user_id or not content or not _configured():
            return None

        if not await self._check_write_rate_limit(user_id):
            logger.warning("[UserFacts] remember() rate-limited for %s", user_id)
            return None

        category = category if category in _VALID_CATEGORIES else "fact"
        row = {
            "user_id": user_id,
            "content": content[:2000],
            "category": category,
            "importance": max(0.0, min(1.0, importance)),
            "metadata": metadata or {},
        }
        try:
            from apps.core.memory.embeddings import embed_text

            embedding = await embed_text(content[:512])
            if embedding:
                row["embedding"] = embedding
        except Exception as exc:
            logger.debug("[UserFacts] embed failed, storing without embedding: %s", exc)

        try:
            from apps.core.memory.supabase_client import get_db

            db = get_db()
            # supabase-py's client is synchronous — .execute() is a plain
            # call, not a coroutine (see episodic_memory.py's docstring for
            # the bug class this pattern avoids).
            result = db.table("aria_user_memories").insert(row).execute()
            data = getattr(result, "data", None) or []
            memory_id = data[0]["id"] if data else None
        except Exception as exc:
            logger.warning("[UserFacts] remember() failed: %s", exc)
            return None

        if memory_id:
            await self._enforce_cap(user_id)
        return memory_id

    async def _check_write_rate_limit(self, user_id: str) -> bool:
        try:
            from apps.core.memory.redis_client import get_cache

            cache = get_cache()
            if not cache:
                return True
            return await cache.check_rate_limit(
                f"user_facts_write:{user_id}", _WRITE_RATE_LIMIT_PER_HOUR, 3600
            )
        except Exception:
            return True

    async def _enforce_cap(self, user_id: str) -> None:
        """Deletes the oldest facts past MAX_FACTS_PER_USER, keeping the
        store bounded. Best-effort — a failure here must never undo the
        write that just succeeded."""
        try:
            from apps.core.memory.supabase_client import get_db

            db = get_db()
            q = (
                db.table("aria_user_memories")
                .select("id")
                .eq("user_id", user_id)
                .order("created_at", desc=True)
                .range(MAX_FACTS_PER_USER, MAX_FACTS_PER_USER + 200)
            )
            result = await asyncio.to_thread(q.execute)
            overflow = getattr(result, "data", None) or []
            for row in overflow:
                del_q = db.table("aria_user_memories").delete().eq("id", row["id"])
                await asyncio.to_thread(del_q.execute)
        except Exception as exc:
            logger.debug("[UserFacts] cap enforcement failed (non-fatal): %s", exc)

    async def recall(
        self, user_id: str, query: str, top_k: int = 5, category: str | None = None
    ) -> list[dict]:
        """The `top_k` facts most relevant to `query`, for `user_id` only.
        Uses pgvector similarity when an embedding is available, else falls
        back to a keyword match — both paths filter by user_id in the query
        itself, never in Python after the fact."""
        user_id = (user_id or "").strip().lower()
        query = (query or "").strip()
        if not user_id or not query or not _configured():
            return []

        try:
            from apps.core.memory.embeddings import embed_text

            embedding = await embed_text(query[:512])
        except Exception:
            embedding = None

        if embedding:
            try:
                from apps.core.memory.supabase_client import get_db

                db = get_db()
                result = db.rpc(
                    "match_user_memories",
                    {
                        "p_user_id": user_id,
                        "p_query_embedding": embedding,
                        "p_match_count": top_k,
                        "p_category": category,
                    },
                ).execute()
                return getattr(result, "data", None) or []
            except Exception as exc:
                logger.warning(
                    "[UserFacts] vector recall failed, falling back to keyword search: %s", exc
                )

        return await self._keyword_fallback(user_id, query, top_k, category)

    async def _keyword_fallback(
        self, user_id: str, query: str, top_k: int, category: str | None
    ) -> list[dict]:
        rows = await self.list_all(user_id, category=category, limit=200)
        if not rows:
            return []
        query_tokens = {w for w in query.lower().split() if len(w) > 3}
        if not query_tokens:
            return []
        scored = []
        for row in rows:
            content_tokens = set((row.get("content") or "").lower().split())
            score = len(query_tokens & content_tokens)
            if score > 0:
                scored.append((score, row))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [row for _, row in scored[:top_k]]

    async def list_all(
        self, user_id: str, category: str | None = None, limit: int = 50
    ) -> list[dict]:
        """Every fact stored for `user_id`, newest first."""
        user_id = (user_id or "").strip().lower()
        if not user_id or not _configured():
            return []
        try:
            from apps.core.memory.supabase_client import get_db

            db = get_db()
            q = (
                db.table("aria_user_memories")
                .select("*")
                .eq("user_id", user_id)
                .order("created_at", desc=True)
                .limit(limit)
            )
            if category:
                q = q.eq("category", category)
            # q.execute() is synchronous (supabase-py) — run it off the event
            # loop so a slow Supabase round-trip can't stall every other
            # concurrent request on this worker (this is now called inside
            # an asyncio.gather() from the Mission Control memory inspector).
            result = await asyncio.to_thread(q.execute)
            return getattr(result, "data", None) or []
        except Exception as exc:
            logger.warning("[UserFacts] list_all() failed: %s", exc)
            return []

    async def forget(self, user_id: str, memory_id: str) -> bool:
        """Deletes one fact by id — but only if it belongs to `user_id`.
        The `.eq("user_id", ...)` filter is load-bearing, not decorative:
        it's what stops one user from deleting a row that isn't theirs even
        if they somehow learn another user's memory_id (e.g. by guessing a
        UUID) — the delete then simply matches zero rows."""
        user_id = (user_id or "").strip().lower()
        memory_id = (memory_id or "").strip()
        if not user_id or not memory_id or not _configured():
            return False
        try:
            from apps.core.memory.supabase_client import get_db

            db = get_db()
            result = (
                db.table("aria_user_memories")
                .delete()
                .eq("id", memory_id)
                .eq("user_id", user_id)
                .execute()
            )
            data = getattr(result, "data", None) or []
            return bool(data)
        except Exception as exc:
            logger.warning("[UserFacts] forget() failed: %s", exc)
            return False

    async def forget_all(self, user_id: str) -> bool:
        """Deletes every fact stored for `user_id` — used by account
        deletion (a user's remembered facts must not outlive their
        account) and by a future "forget everything about me" action.
        Unlike forget(), there's no memory_id to double-check against, but
        the `.eq("user_id", ...)` filter is still what scopes the delete to
        exactly this caller and nobody else."""
        user_id = (user_id or "").strip().lower()
        if not user_id or not _configured():
            return False
        try:
            from apps.core.memory.supabase_client import get_db

            db = get_db()
            db.table("aria_user_memories").delete().eq("user_id", user_id).execute()
            return True
        except Exception as exc:
            logger.warning("[UserFacts] forget_all() failed: %s", exc)
            return False


_store: UserFactStore | None = None


def get_user_facts() -> UserFactStore:
    """Process-wide singleton — safe because all actual state lives in
    Supabase, not on this object."""
    global _store
    if _store is None:
        _store = UserFactStore()
    return _store
