"""
mem0_client.py — Intelligent, Adaptive Memory for ARIA AI.

Integrates Mem0 so that ARIA can:
  - Persistently remember user preferences
  - Learn from every past interaction
  - Personalize responses based on historical context
  - Manage a long-term memory that evolves with the user

Reference: https://github.com/mem0ai/mem0
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("aria.mem0")

# ── Mem0 import with fallback ────────────────────────────────────────────────
try:
    from mem0 import Memory

    MEM0_AVAILABLE = True
    logger.info("[Mem0] Library loaded successfully.")
except ImportError:
    MEM0_AVAILABLE = False
    logger.warning("[Mem0] mem0 not installed. Using fallback.")


class AriaMem0Client:
    """
    Mem0 Memory client for ARIA.
    Enables continuous learning about the user.
    """

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = config or {
            "vector_store": {"provider": "qdrant", "config": {"host": "localhost", "port": 6333}},
        }
        self._memory = None

        if MEM0_AVAILABLE:
            try:
                self._memory = Memory.from_config(self.config)
                logger.info("[Mem0] Initialized successfully.")
            except Exception as exc:
                logger.error("[Mem0] Error initializing: %s", exc)

    async def add_memory(self, user_id: str, content: str, metadata: dict[str, Any] | None = None):
        """Adds a fact or interaction to the user's memory."""
        if not self._memory:
            logger.debug("[Mem0] Memory not available. Skipping save.")
            return

        try:
            self._memory.add(content, user_id=user_id, metadata=metadata or {})
            logger.info("[Mem0] Memory added for user %s", user_id)
        except Exception as exc:
            logger.error("[Mem0] Error adding memory: %s", exc)

    async def search_memories(self, user_id: str, query: str) -> list[dict[str, Any]]:
        """Searches the user's memory based on a query."""
        if not self._memory:
            return []

        try:
            return self._memory.search(query, user_id=user_id)
        except Exception as exc:
            logger.error("[Mem0] Error searching memory: %s", exc)
            return []

    async def get_all_memories(self, user_id: str) -> list[dict[str, Any]]:
        """Returns all remembered facts for a user."""
        if not self._memory:
            return []

        try:
            return self._memory.get_all(user_id=user_id)
        except Exception as exc:
            logger.error("[Mem0] Error retrieving memories: %s", exc)
            return []


# ── Singleton ────────────────────────────────────────────────────────────────
_mem0_instance: AriaMem0Client | None = None


def get_mem0_client() -> AriaMem0Client:
    """Returns the Mem0 client singleton."""
    global _mem0_instance
    if _mem0_instance is None:
        _mem0_instance = AriaMem0Client()
    return _mem0_instance
