"""
Thin shim so that `from apps.core.llm.llm_client import complete_json` works
everywhere in the scheduler. Delegates to AIClient.complete_json.
"""

from __future__ import annotations

_MODEL_MAP = {
    "fast": "fast",
    "strategy": "strategy",
    "code": "code",
    "creative": "creative",
    "standard": "strategy",  # alias
}


async def complete_json(
    user: str,
    system: str = "You are a helpful AI assistant. Always return valid JSON only.",
    model: str = "fast",
    **kwargs,
) -> dict | None:
    """Complete an LLM call and return parsed JSON, or None on failure."""
    from apps.core.tools.ai_client import AIModel, get_ai_client

    ai = get_ai_client()
    if ai is None:
        return None
    model_key = _MODEL_MAP.get(model, "strategy")
    ai_model = AIModel(model_key)
    return await ai.complete_json(
        system=system,
        user=user,
        model=ai_model,
    )
