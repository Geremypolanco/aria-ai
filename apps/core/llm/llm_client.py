"""
Thin shim so that `from apps.core.llm.llm_client import complete_json` works
everywhere in the scheduler. Delegates to AIClient.complete_json.
"""
from __future__ import annotations

from typing import Optional


async def complete_json(
    user: str,
    system: str = "You are a helpful AI assistant. Always return valid JSON only.",
    model: str = "fast",
    **kwargs,
) -> Optional[dict]:
    """Complete an LLM call and return parsed JSON, or None on failure."""
    from apps.core.tools.ai_client import get_ai_client, AIModel
    ai = get_ai_client()
    if ai is None:
        return None
    return await ai.complete_json(
        system=system,
        user=user,
        model=AIModel.STANDARD,
    )
