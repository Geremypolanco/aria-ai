"""
langfuse_client.py — LLM Observability and Tracing for ARIA AI.

Integrates Langfuse for:
  - Detailed tracing of every LLM call (traces)
  - Monitoring of costs and token usage
  - Evaluation of agent latency and performance
  - Debugging of complex multi-step flows

Reference: https://langfuse.com/docs/sdk/python
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("aria.langfuse")

# ── Langfuse Import with fallback ────────────────────────────────────────────
try:
    from langfuse import Langfuse

    LANGFUSE_AVAILABLE = True
    logger.info("[Langfuse] SDK loaded successfully.")
except ImportError:
    LANGFUSE_AVAILABLE = False
    logger.warning("[Langfuse] langfuse not installed.")


class AriaLangfuseClient:
    """
    Langfuse observability client for ARIA.
    Centralizes monitoring of all interactions with language models.
    """

    def __init__(
        self, public_key: str = "", secret_key: str = "", host: str = "https://cloud.langfuse.com"
    ) -> None:
        self.public_key = public_key
        self.secret_key = secret_key
        self.host = host
        self._client = None

        if LANGFUSE_AVAILABLE and public_key and secret_key:
            try:
                self._client = Langfuse(public_key=public_key, secret_key=secret_key, host=host)
                logger.info("[Langfuse] Initialized at %s", host)
            except Exception as exc:
                logger.error("[Langfuse] Error initializing: %s", exc)

    def trace_interaction(
        self,
        name: str,
        user_id: str,
        input_data: Any,
        output_data: Any,
        metadata: dict[str, Any] | None = None,
    ):
        """Records a complete interaction trace."""
        if not self._client:
            logger.debug("[Langfuse] Simulated trace for: %s", name)
            return

        try:
            self._client.trace(
                name=name,
                user_id=user_id,
                input=input_data,
                output=output_data,
                metadata=metadata or {},
            )
            logger.info("[Langfuse] Trace recorded: %s", name)
        except Exception as exc:
            logger.error("[Langfuse] Error recording trace: %s", exc)


# ── Singleton ────────────────────────────────────────────────────────────────
_langfuse_instance: AriaLangfuseClient | None = None


def get_langfuse_client() -> AriaLangfuseClient:
    """Returns the singleton Langfuse client."""
    global _langfuse_instance
    if _langfuse_instance is None:
        import os

        _langfuse_instance = AriaLangfuseClient(
            public_key=os.getenv("LANGFUSE_PUBLIC_KEY", ""),
            secret_key=os.getenv("LANGFUSE_SECRET_KEY", ""),
            host=os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com"),
        )
    return _langfuse_instance
