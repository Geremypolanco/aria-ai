"""
Platform AI abstraction — provider-agnostic LLM interface.

Wraps the existing AIClient behind a stable interface so callers never import
a specific provider directly. Switching from HuggingFace → Groq → Anthropic
requires only changing this module, not every call site.

The interface deliberately models the minimal contract:
  - complete(prompt, system, max_tokens) → str
  - complete_json(prompt, system, schema) → dict
  - embed(text) → list[float]

Richer features (streaming, tool-use) are added as optional methods that
callers can detect via hasattr() — no breaking changes to existing callers.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("aria.platform.ai")


class AIProvider:
    """Thin facade over the concrete AI client."""

    def __init__(self, client: Any) -> None:
        self._client = client

    async def complete(
        self,
        prompt: str,
        system: str = "",
        max_tokens: int = 1000,
        temperature: float = 0.7,
    ) -> str:
        if self._client is None:
            return ""
        try:
            result = await self._client.complete(
                prompt=prompt,
                system=system,
                max_tokens=max_tokens,
                temperature=temperature,
            )
            if hasattr(result, "content"):
                return result.content or ""
            return str(result) if result else ""
        except Exception as exc:
            logger.error("[Platform.AI] complete failed: %s", exc)
            return ""

    async def complete_json(
        self,
        prompt: str,
        system: str = "",
        schema: dict | None = None,
    ) -> dict:
        if self._client is None:
            return {}
        try:
            return (
                await self._client.complete_json(
                    prompt=prompt,
                    system=system,
                    schema=schema or {},
                )
                or {}
            )
        except Exception as exc:
            logger.error("[Platform.AI] complete_json failed: %s", exc)
            return {}

    async def embed(self, text: str) -> list[float]:
        if self._client is None:
            return []
        try:
            if hasattr(self._client, "embed"):
                return await self._client.embed(text) or []
            return []
        except Exception as exc:
            logger.error("[Platform.AI] embed failed: %s", exc)
            return []

    @property
    def available(self) -> bool:
        return self._client is not None

    @property
    def provider_name(self) -> str:
        if self._client is None:
            return "none"
        return getattr(self._client, "provider", type(self._client).__name__)


_provider: AIProvider | None = None


def get_ai_provider(client: Any = None) -> AIProvider:
    global _provider
    if _provider is None:
        if client is None:
            try:
                from apps.core.tools.ai_client import get_ai_client

                client = get_ai_client()
            except Exception:
                client = None
        _provider = AIProvider(client)
    return _provider
