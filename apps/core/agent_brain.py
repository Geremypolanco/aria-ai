"""
ARIA AI — Agent Brain v3.2.
Fully integrated with Tool Registry, HuggingFace/Groq/OpenAI, and orchestrator.
"""

from __future__ import annotations

import logging
from typing import Any

from apps.core.tool_registry import SYSTEM_INSTRUCTION, get_tool_descriptions
from apps.core.tools.ai_client import AIModel, get_ai_client

logger = logging.getLogger("aria.agent")


# ── FULL SYSTEM PROMPT ───────────────────────────────────
def build_system_prompt(include_tools: bool = True) -> str:
    base = SYSTEM_INSTRUCTION
    if include_tools:
        base += "\n\n" + get_tool_descriptions()
    return base


class AriaAgent:
    """ARIA's main agent - uses local AI models with full tool-use capability."""

    def __init__(self):
        self.client = get_ai_client()
        logger.info("AriaAgent v3.2 initialized")

    async def think(
        self,
        message: str,
        system: str | None = None,
        model: AIModel = AIModel.STRATEGY,
        temperature: float = 0.7,
        max_tokens: int = 8192,
    ) -> str:
        """Process a message through ARIA's reasoning with multi-provider fallback."""
        if not self.client:
            return """⚠️ **ARIA is not fully initialized**

To activate all my capabilities, configure at least one of these API keys in your `.env`:
- `HF_TOKEN` (HuggingFace - primary engine, free)
- `GROQ_API_KEY` (Groq - fast fallback)
- `OPENAI_API_KEY` (OpenAI - secondary fallback)

In the meantime, you can use the dashboard to see the system status."""

        full_system = system or build_system_prompt()
        try:
            response = await self.client.complete(
                system=full_system,
                user=message,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
                agent_name="aria",
            )
            if response and response.success:
                return response.content
            # If primary fails, try fallback
            fb_response = await self.client.complete(
                system=full_system,
                user=message,
                model=AIModel.FAST,
                temperature=temperature,
                max_tokens=max_tokens,
                agent_name="aria-fallback",
            )
            if fb_response and fb_response.success:
                return fb_response.content
            logger.error(
                "All AI providers failed: %s", response.error if response else "no response"
            )
            return "⚠️ All AI providers failed. Try again in a moment."
        except Exception as e:
            logger.error(f"AriaAgent.think error: {e}")
            return """⚠️ **Internal error**

Possible causes:
- Invalid API key or out of funds
- Connection timeout
- Model temporarily unavailable

Try again or check your configuration."""

    async def think_json(
        self,
        message: str,
        system: str | None = None,
        model: AIModel = AIModel.STRATEGY,
    ) -> dict[str, Any]:
        """Get structured JSON response from ARIA."""
        if not self.client:
            return {"error": "AI not initialized"}
        try:
            response = await self.client.complete_json(
                system=system or build_system_prompt(),
                user=message,
                model=model,
            )
            return response or {"error": "Empty response"}
        except Exception as e:
            logger.error(f"think_json error: {e}")
            return {"error": str(e)}

    async def generate_code(
        self,
        prompt: str,
        language: str = "python",
    ) -> str:
        """Generate code using ARIA's code-optimized model."""
        system = f"""You are a software engineer expert in {language.upper()}.

GUIDELINES:
1. Generate clean, efficient, well-documented code
2. Follow {language} best practices
3. Include error handling
4. Add explanatory comments
5. If applicable, include usage examples

Target language: {language}"""
        return await self.think(
            message=prompt,
            system=system,
            model=AIModel.CODE,
            temperature=0.2,
            max_tokens=8192,
        )

    async def research(
        self,
        topic: str,
        depth: str = "complete",
    ) -> str:
        """Deep research on any topic."""
        system = f"""You are an expert academic researcher conducting {depth} research on: {topic}

RESPONSE STRUCTURE:
1. **Executive Summary** - Overview in 2-3 sentences
2. **Context and Background** - Necessary foundational information
3. **Main Analysis** - Detailed breakdown of the topic
4. **Key Findings** - The most important discoveries
5. **Implications** - What this means in practice
6. **Conclusions** - Final synthesis
7. **References** - Sources and additional resources"""
        return await self.think(
            message=f"Research thoroughly: {topic}",
            system=system,
            model=AIModel.STRATEGY,
            temperature=0.3,
            max_tokens=8192,
        )

    async def analyze(
        self,
        data: str,
        analysis_type: str = "general",
    ) -> str:
        """Analyze data, code, text, or any content."""
        system = f"""You are an expert analyst performing a {analysis_type} analysis

Provide:
1. Summary of what is being analyzed
2. Key points and patterns identified
3. Problems or areas for improvement (if applicable)
4. Actionable recommendations
5. Overall score or evaluation"""
        return await self.think(
            message=data,
            system=system,
            model=AIModel.STRATEGY,
            temperature=0.3,
        )


# ── SINGLETON ─────────────────────────────────────────────
_agent: AriaAgent | None = None


def get_agent() -> AriaAgent:
    global _agent
    if _agent is None:
        _agent = AriaAgent()
    return _agent
