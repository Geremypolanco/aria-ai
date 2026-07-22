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
            return """⚠️ **ARIA no está completamente inicializada**

Para activar todas mis capacidades, configura al menos una de estas API keys en tu `.env`:
- `HF_TOKEN` (HuggingFace - motor principal, gratis)
- `GROQ_API_KEY` (Groq - respaldo rápido)
- `OPENAI_API_KEY` (OpenAI - respaldo secundario)

Mientras tanto, puedes usar el dashboard para ver el estado del sistema."""

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
            return "⚠️ Todos los proveedores de IA fallaron. Intenta de nuevo en un momento."
        except Exception as e:
            logger.error(f"AriaAgent.think error: {e}")
            return """⚠️ **Error interno**

Posibles causas:
- API key inválida o sin fondos
- Timeout en la conexión
- Modelo temporalmente no disponible

Intenta de nuevo o verifica tu configuración."""

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
        system = f"""Eres un ingeniero de software experto en {language.upper()}.

DIRECTRICES:
1. Genera código limpio, eficiente y bien documentado
2. Sigue las mejores prácticas de {language}
3. Incluye manejo de errores
4. Agrega comentarios explicativos
5. Si es aplicable, incluye ejemplos de uso

Lenguaje objetivo: {language}"""
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
        depth: str = "completa",
    ) -> str:
        """Deep research on any topic."""
        system = f"""Eres un investigador académico experto realizando una investigación {depth} sobre: {topic}

ESTRUCTURA DE RESPUESTA:
1. **Resumen Ejecutivo** - Visión general en 2-3 oraciones
2. **Contexto y Antecedentes** - Información fundamental necesaria
3. **Análisis Principal** - Desglose detallado del tema
4. **Hallazgos Clave** - Los descubrimientos más importantes
5. **Implicaciones** - Qué significa esto en la práctica
6. **Conclusiones** - Síntesis final
7. **Referencias** - Fuentes y recursos adicionales"""
        return await self.think(
            message=f"Investiga a fondo: {topic}",
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
        system = f"""Eres un analista experto realizando un análisis de tipo: {analysis_type}

Proporciona:
1. Resumen de lo que se está analizando
2. Puntos clave y patrones identificados
3. Problemas o áreas de mejora (si aplica)
4. Recomendaciones accionables
5. Puntuación o evaluación general"""
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
