"""
Dead-letter queue for LLM outputs that never validated.

A structured output that fails schema validation after all retries lands
here, visible to operators — it never silently enters a report, a product
listing, or a price. Mirrors ``dead-letter.ts`` from
``@polanco/llm-contracts``.
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime

logger = logging.getLogger("aria.llm_contracts")


@dataclass
class DeadLetterEntry:
    """One quarantined LLM output."""

    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    schema: str = "unknown"
    errors: list[str] = field(default_factory=list)
    attempts: int = 0
    agent: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict) -> DeadLetterEntry:
        return cls(
            id=str(raw.get("id", uuid.uuid4().hex)),
            at=str(raw.get("at", "")),
            schema=str(raw.get("schema", "unknown")),
            errors=list(raw.get("errors", []) or []),
            attempts=int(raw.get("attempts", 0) or 0),
            agent=str(raw.get("agent", "") or ""),
        )


class DeadLetterQueue:
    """In-memory dead-letter queue.

    Push failed outputs here; the health summary exposes them for human
    triage. Nothing here ever reaches a client report or a money boundary.
    """

    def __init__(self) -> None:
        self._entries: list[DeadLetterEntry] = []

    def push(self, entry: DeadLetterEntry) -> None:
        self._entries.append(entry)
        logger.warning(
            "[dead-letter] quarantined output for schema=%s agent=%s "
            "attempts=%d errors=%s",
            entry.schema,
            entry.agent or "-",
            entry.attempts,
            "; ".join(entry.errors[:3]),
        )
        # L2 durable sink (Supabase) — best effort, never raises, never
        # blocks. The in-memory queue above stays the source of truth; the
        # store degrades to a logged warning when Supabase is unconfigured
        # or unreachable, so entries survive worker restarts when it is.
        # Lazy import: dead_letter_store imports this module at its top
        # level, so a top-level import here would be circular.
        try:
            from apps.core.llm.contracts.dead_letter_store import get_dead_letter_store

            get_dead_letter_store().persist(entry)
        except Exception:  # noqa: BLE001 — the entry is already safe above
            logger.debug("[dead-letter] persistent sink unavailable", exc_info=True)

    def list(self) -> list[DeadLetterEntry]:
        return list(self._entries)

    def clear(self) -> None:
        self._entries.clear()

    def __len__(self) -> int:
        return len(self._entries)

    def to_json(self) -> str:
        return json.dumps([e.to_dict() for e in self._entries])

    @classmethod
    def from_json(cls, payload: str) -> DeadLetterQueue:
        queue = cls()
        parsed = json.loads(payload)
        if isinstance(parsed, list):
            for raw in parsed:
                if isinstance(raw, dict):
                    queue._entries.append(DeadLetterEntry.from_dict(raw))
        return queue


_QUEUE: DeadLetterQueue | None = None


def get_dead_letter_queue() -> DeadLetterQueue:
    """Process-wide singleton dead-letter queue (visible, never silent)."""
    global _QUEUE
    if _QUEUE is None:
        _QUEUE = DeadLetterQueue()
    return _QUEUE
