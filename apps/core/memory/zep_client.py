"""
zep_client.py — Long-Term Memory for ARIA AI with Zep.

Zep provides long-term memory for agents with:
  - Context graphs with sub-200ms retrieval
  - Management of users, threads, and messages
  - Automatic extraction of facts and relationships
  - Integration with LangChain, AutoGen, CrewAI

Integration with Aria:
  - Complements the existing EvolutionaryMemory (Mem0-inspired)
  - Provides persistent memory across Telegram sessions
  - Stores the interaction history per user/agent
  - Retrieves relevant context for each new task

Reference: https://github.com/getzep/zep
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger("aria.zep_client")

# ── Zep import with fallback ─────────────────────────────────────────────────
try:
    from zep_cloud.client import AsyncZep
    from zep_cloud.types import Message, RoleType  # noqa: F401

    ZEP_AVAILABLE = True
    logger.info("[Zep] zep-cloud library loaded successfully.")
except ImportError:
    try:
        # Try zep-python (community version)
        from zep_python.client import AsyncZep  # type: ignore[no-redef]

        ZEP_AVAILABLE = True
        logger.info("[Zep] zep-python library loaded successfully.")
    except ImportError:
        ZEP_AVAILABLE = False
        logger.warning(
            "[Zep] zep-cloud not installed. "
            "Using Supabase memory as fallback. "
            "Install with: pip install zep-cloud"
        )
        AsyncZep = None  # type: ignore[assignment,misc]


# ── Supabase Fallback Implementation ─────────────────────────────────────────


class SupabaseMemoryFallback:
    """
    Memory fallback using Supabase (already available in Aria).
    Keeps the same interface as Zep for compatibility.
    """

    def __init__(self) -> None:
        self._sessions: dict[str, list[dict]] = {}

    async def add_memory(self, session_id: str, messages: list[dict]) -> None:
        if session_id not in self._sessions:
            self._sessions[session_id] = []
        self._sessions[session_id].extend(messages)

        # Persist to Supabase if available
        try:
            from apps.core.memory.supabase_client import get_db

            db = get_db()
            for msg in messages:
                await db.log_error(
                    f"[ZepFallback] session={session_id} role={msg.get('role')} "
                    f"content={msg.get('content', '')[:100]}"
                )
        except Exception:
            pass

    async def get_memory(self, session_id: str, limit: int = 10) -> list[dict]:
        msgs = self._sessions.get(session_id, [])
        return msgs[-limit:]

    async def search_memory(self, session_id: str, query: str, limit: int = 5) -> list[dict]:
        msgs = self._sessions.get(session_id, [])
        query_lower = query.lower()
        results = [m for m in msgs if query_lower in m.get("content", "").lower()]
        return results[-limit:]


# ── Main Zep Client for ARIA ─────────────────────────────────────────────────


class AriaZepClient:
    """
    Zep client for ARIA AI.

    Manages the agents' long-term memory, enabling:
    - Recalling past conversations with Telegram users
    - Maintaining campaign and strategy context across sessions
    - Retrieving relevant facts for new tasks
    - Building user and customer profiles

    Usage:
        client = AriaZepClient()

        # Add messages to memory
        await client.add_interaction(
            session_id="user_123",
            role="user",
            content="I want to create an ebook about fitness"
        )

        # Retrieve relevant context
        context = await client.get_relevant_context(
            session_id="user_123",
            query="monetization strategy"
        )
    """

    def __init__(self, api_key: str = "") -> None:
        self._client: Any = None
        self._fallback: SupabaseMemoryFallback | None = None
        self._api_key = api_key
        self._initialized = False

    async def initialize(self) -> bool:
        """
        Initializes the connection to Zep Cloud or uses the fallback.
        Returns True if Zep is available, False if using the fallback.
        """
        if not ZEP_AVAILABLE or not self._api_key:
            logger.info(
                "[Zep] Using Supabase fallback (ZEP_API_KEY not configured or zep-cloud not installed)"
            )
            self._fallback = SupabaseMemoryFallback()
            self._initialized = True
            return False

        try:
            self._client = AsyncZep(api_key=self._api_key)
            self._initialized = True
            logger.info("[Zep] Connection to Zep Cloud established")
            return True
        except Exception as exc:
            logger.warning("[Zep] Error connecting to Zep Cloud: %s — using fallback", exc)
            self._fallback = SupabaseMemoryFallback()
            self._initialized = True
            return False

    async def ensure_session(self, session_id: str, user_id: str | None = None) -> bool:
        """
        Ensures a session exists in Zep.

        Args:
            session_id: Unique session ID (e.g.: telegram_chat_id)
            user_id: User ID (optional)
        """
        if not self._initialized:
            await self.initialize()

        if self._client:
            try:
                await self._client.memory.add_session(
                    session_id=session_id,
                    user_id=user_id or session_id,
                )
                return True
            except Exception:
                # The session may already exist
                return True
        return True

    async def add_interaction(
        self,
        session_id: str,
        role: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        """
        Adds an interaction to long-term memory.

        Args:
            session_id: Session ID (e.g.: telegram_chat_id, agent_name)
            role: "user", "assistant", "system", or the agent's name
            content: Message content
            metadata: Additional data (agent_name, task_type, roi, etc.)

        Returns:
            True if added successfully
        """
        if not self._initialized:
            await self.initialize()

        message_dict = {
            "role": role,
            "content": content,
            "timestamp": datetime.now(UTC).isoformat(),
            "metadata": metadata or {},
        }

        try:
            if self._client:
                await self.ensure_session(session_id)
                # Zep Cloud API
                messages = [
                    {
                        "role": role if role in ("user", "assistant") else "assistant",
                        "role_type": "user" if role == "user" else "assistant",
                        "content": content,
                    }
                ]
                await self._client.memory.add(
                    session_id=session_id,
                    messages=messages,
                )
            elif self._fallback:
                await self._fallback.add_memory(session_id, [message_dict])

            logger.debug("[Zep] Interaction added: session=%s role=%s", session_id, role)
            return True

        except Exception as exc:
            logger.error("[Zep] Error adding interaction: %s", exc)
            return False

    async def get_relevant_context(
        self,
        session_id: str,
        query: str,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        """
        Retrieves relevant context from memory for a query.

        Args:
            session_id: Session ID
            query: Semantic search query
            limit: Maximum number of results

        Returns:
            List of relevant messages/facts
        """
        if not self._initialized:
            await self.initialize()

        try:
            if self._client:
                results = await self._client.memory.search_sessions(
                    text=query,
                    session_ids=[session_id],
                    limit=limit,
                )
                return [
                    {
                        "content": r.message.content if hasattr(r, "message") else str(r),
                        "score": r.score if hasattr(r, "score") else 0.0,
                        "session_id": session_id,
                    }
                    for r in (results or [])
                ]
            if self._fallback:
                return await self._fallback.search_memory(session_id, query, limit)

        except Exception as exc:
            logger.error("[Zep] Error searching context: %s", exc)

        return []

    async def get_session_history(
        self,
        session_id: str,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """
        Gets the full history of a session.

        Args:
            session_id: Session ID
            limit: Maximum number of messages

        Returns:
            List of messages in chronological order
        """
        if not self._initialized:
            await self.initialize()

        try:
            if self._client:
                memory = await self._client.memory.get(session_id=session_id)
                if memory and hasattr(memory, "messages"):
                    return [
                        {
                            "role": m.role if hasattr(m, "role") else "unknown",
                            "content": m.content if hasattr(m, "content") else str(m),
                            "timestamp": (
                                m.created_at.isoformat() if hasattr(m, "created_at") else ""
                            ),
                        }
                        for m in (memory.messages or [])[-limit:]
                    ]
            elif self._fallback:
                return await self._fallback.get_memory(session_id, limit)

        except Exception as exc:
            logger.error("[Zep] Error retrieving history: %s", exc)

        return []

    async def record_agent_action(
        self,
        agent_name: str,
        action: str,
        result: str,
        success: bool,
        roi: float = 0.0,
    ) -> bool:
        """
        Records an agent action in long-term memory.
        Allows ARIA to learn from its own past actions.

        Args:
            agent_name: Agent name (orchestrator, cfo, marketing, etc.)
            action: Description of the action performed
            result: Result obtained
            success: Whether the action was successful
            roi: ROI generated in USD
        """
        session_id = f"agent_{agent_name}"
        content = (
            f"[{'✓' if success else '✗'}] {action} | "
            f"Result: {result[:200]} | "
            f"ROI: ${roi:.2f}"
        )
        return await self.add_interaction(
            session_id=session_id,
            role="assistant",
            content=content,
            metadata={
                "agent": agent_name,
                "success": success,
                "roi": roi,
                "timestamp": datetime.now(UTC).isoformat(),
            },
        )

    async def get_agent_learnings(
        self,
        agent_name: str,
        query: str,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        """
        Retrieves past learnings from a specific agent.

        Args:
            agent_name: Agent name
            query: Topic to search for in memory
            limit: Maximum number of results
        """
        session_id = f"agent_{agent_name}"
        return await self.get_relevant_context(session_id, query, limit)

    async def get_status(self) -> dict[str, Any]:
        """Returns the Zep client's status."""
        return {
            "backend": "zep_cloud" if self._client else "supabase_fallback",
            "zep_available": ZEP_AVAILABLE,
            "initialized": self._initialized,
            "api_key_configured": bool(self._api_key),
        }


# ── Singleton ────────────────────────────────────────────────────────────────
_zep_instance: AriaZepClient | None = None


def get_zep_client() -> AriaZepClient:
    """Returns ARIA's Zep client singleton."""
    global _zep_instance
    if _zep_instance is None:
        import os

        _zep_instance = AriaZepClient(
            api_key=os.getenv("ZEP_API_KEY", ""),
        )
    return _zep_instance
