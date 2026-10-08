"""
Persistent dead-letter sink (Supabase) — cuspide wave 3.

The in-memory :class:`DeadLetterQueue` is the L1 fast path; this module is
the durable L2. Every :meth:`DeadLetterQueue.push` also attempts a
best-effort write here so quarantined LLM outputs survive worker restarts
and are visible to sibling workers/operators via the ``dead_letters``
table (see ``database/dead_letters.sql``).

Design notes:

- **Never raises, never blocks the caller.** When Supabase is unconfigured
  or unreachable the store degrades to a logged warning (once per process)
  and the in-memory queue remains the source of truth.
- **Lazy.** No Supabase client is constructed at import time; the client is
  built on first use so unit tests and degraded boots never pay for it.
- **No secrets in code.** Credentials come only from ``SUPABASE_URL`` /
  ``SUPABASE_KEY`` env vars (see ``apps.core.config``).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from apps.core.llm.contracts.dead_letter import DeadLetterEntry

logger = logging.getLogger("aria.llm_contracts")

_TABLE = "dead_letters"


class DeadLetterStore:
    """Best-effort durable sink for dead-letter entries."""

    def __init__(self, db: Any | None = None) -> None:
        # ``db`` injection is for tests; production lazily builds AriaDatabase.
        self._db = db
        self._warned_unavailable = False
        self._warned_write_failed = False

    # ── availability ──────────────────────────────────────────────────

    def _client(self) -> Any | None:
        if self._db is not None:
            return self._db
        try:
            from apps.core.config import settings

            # Repo rule: tests NEVER touch the real network. The test suite
            # sets fake SUPABASE_URL/KEY, so gate on ENVIRONMENT too —
            # otherwise every dead-letter push would attempt a real HTTP
            # write to a fake host.
            if getattr(settings, "ENVIRONMENT", "") == "test":
                return None
            if not (getattr(settings, "SUPABASE_URL", None) and getattr(settings, "SUPABASE_KEY", None)):
                return None
            from apps.core.memory.supabase_client import AriaDatabase

            self._db = AriaDatabase()
            return self._db
        except Exception as exc:  # noqa: BLE001 — degraded mode, never fatal
            logger.debug("[dead-letter-store] supabase unavailable: %s", exc)
            return None

    def available(self) -> bool:
        """True when a Supabase backend can be reached (credentials set)."""
        return self._client() is not None

    def _note_unavailable(self) -> None:
        if not self._warned_unavailable:
            logger.warning(
                "[dead-letter-store] SUPABASE_URL/SUPABASE_KEY not configured — "
                "dead letters stay in-memory only. Apply database/dead_letters.sql "
                "and set the env vars to enable the persistent sink."
            )
            self._warned_unavailable = True

    # ── writes ────────────────────────────────────────────────────────

    def persist(self, entry: DeadLetterEntry) -> bool:
        """Write one entry to Supabase. Returns True on success.

        Never raises: on any failure the entry simply stays in the
        in-memory queue (the caller already pushed it there).
        """
        db = self._client()
        if db is None:
            self._note_unavailable()
            return False
        try:
            db.table(_TABLE).insert(
                {
                    "id": entry.id,
                    "at": entry.at,
                    "schema": entry.schema,
                    "errors": entry.errors,
                    "attempts": entry.attempts,
                    "agent": entry.agent,
                }
            ).execute()
            return True
        except Exception as exc:  # noqa: BLE001 — best effort by design
            if not self._warned_write_failed:
                logger.warning(
                    "[dead-letter-store] write failed (in-memory queue still holds "
                    "the entry): %s",
                    exc,
                )
                self._warned_write_failed = True
            return False

    # ── reads (health summary / operator triage) ──────────────────────

    def count(self) -> int | None:
        """Total persisted dead letters, or None when the sink is unavailable."""
        db = self._client()
        if db is None:
            return None
        try:
            res = db.table(_TABLE).select("id", count="exact").limit(1).execute()
            count = getattr(res, "count", None)
            return int(count) if count is not None else len(res.data or [])
        except Exception as exc:  # noqa: BLE001
            logger.debug("[dead-letter-store] count failed: %s", exc)
            return None

    def recent(self, limit: int = 5) -> list[dict[str, Any]]:
        """Most recent persisted entries (for the health summary)."""
        db = self._client()
        if db is None:
            return []
        try:
            res = (
                db.table(_TABLE)
                .select("*")
                .order("at", desc=True)
                .limit(max(1, int(limit)))
                .execute()
            )
            return list(res.data or [])
        except Exception as exc:  # noqa: BLE001 — best effort by design
            logger.debug("[dead-letter-store] recent failed: %s", exc)
            return []


_STORE: DeadLetterStore | None = None


def get_dead_letter_store() -> DeadLetterStore:
    """Process-wide singleton persistent sink (best-effort, never raises)."""
    global _STORE
    if _STORE is None:
        _STORE = DeadLetterStore()
    return _STORE
