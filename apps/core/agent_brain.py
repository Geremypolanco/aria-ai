"""
ARIA AI — Agent Brain v3.
Uses the local AI client (HuggingFace / Groq / OpenAI) with proper tool-use prompting.
No external API dependencies beyond what's configured.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from apps.core.config import settings
from apps.core.tools.ai_client import AIModel, AriaAIClient, get_ai_client

logger = logging.getLogger("aria.agent")

# ── SYSTEM PROMPT ─────────────────────────────────────────
SYSTEM_PROMPT = """Eres ARIA, una inteligencia artificial autónoma de nivel enterprise.

CAPACIDADES:
- Razonamiento profundo multi-paso
- Generación y análisis de código
- Investigación y síntesis de información
- Análisis de imágenes y video
- Integración con APIs externas
- Memoria persistente y contextual

DIRECTRICES:
1. Piensa paso a paso antes de responder
2. Si necesitas información, investiga antes de concluir
3. Cuando generes código, incluye explicaciones
4. Sé precisa, honesta y directa
5. Si no sabes algo, dilo claramente
6. Usa las herramientas disponibles cuando sean necesarias

FORMATO DE RESPUESTA:
- Usa **negritas** para énfasis
- Usa `código` para fragmentos de código
- Usa ``` para bloques de código con el lenguaje especificado
- Usa listas numeradas para pasos secuenciales
- Sé conversacional pero profesional"""


class AriaAgent:
    """Agente principal de ARIA que usa el AI client local."""

    def __init__(self):
        self.client: AriaAIClient | None = get_ai_client()
        logger.info("AriaAgent initialized")

    async def think(
        self,
        message: str,
        system: str | None = None,
        model: AIModel = AIModel.STRATEGY,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> str:
        """Process a message through ARIA's reasoning."""
        if self.client is None:
            return "⏳ Error: AI client not initialized. Check your API keys in .env"

        try:
            response = await self.client.complete(
                system=system or SYSTEM_PROMPT,
                user=message,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            return response.content
        except Exception as e:
            logger.error(f"AriaAgent.think error: {e}")
            return f"⚠️ Error processing request: {str(e)}"

    async def think_json(
        self,
        message: str,
        system: str | None = None,
        model: AIModel = AIModel.STRATEGY,
    ) -> dict[str, Any]:
        """Process a message and return structured JSON."""
        json_system = (system or SYSTEM_PROMPT) + "\n\nRESPONDE SOLO CON JSON VÁLIDO."
        response = await self.think(
            message=message,
            system=json_system,
            model=model,
            temperature=0.1,
        )
        return self._parse_json(response)

    async def generate_code(
        self,
        prompt: str,
        language: str = "python",
    ) -> str:
        """Generate code with ARIA's code model."""
        system = f"Eres un experto programador en {language}. Genera código limpio, bien documentado y funcional."
        return await self.think(
            message=prompt,
            system=system,
            model=AIModel.CODE,
            temperature=0.2,
        )

    async def analyze_image(
        self,
        image_base64: str,
        question: str,
    ) -> str:
        """Analyze an image with ARIA's vision capabilities."""
        if self.client is None:
            return "Vision not available"
        try:
            return await self.client.analyze_image(image_base64, question)
        except Exception as e:
            logger.error(f"Vision error: {e}")
            return f"Vision analysis failed: {e}"

    async def research(
        self,
        topic: str,
        depth: str = "medium",
    ) -> str:
        """Research a topic in depth."""
        system = f"""Eres un investigador experto. Investiga a fondo sobre: {topic}

PROFUNDIDAD: {depth}

Estructura tu respuesta:
1. Resumen ejecutivo
2. Hallazgos principales
3. Análisis detallado
4. Conclusiones y recomendaciones
5. Fuentes y referencias"""
        return await self.think(
            message=f"Realiza una investigación profunda sobre: {topic}",
            system=system,
            model=AIModel.STRATEGY,
            temperature=0.3,
            max_tokens=8192,
        )

    @staticmethod
    def _parse_json(text: str) -> dict[str, Any]:
        """Extrae JSON del texto."""
        text = text.strip()
        text = re.sub(r"```(?:json)?\n?", "", text).strip().rstrip("```").strip()
        for start, end in [("{", "}"), ("[", "]")]:
            s = text.find(start)
            if s != -1:
                e = text.rfind(end)
                if e > s:
                    try:
                        return json.loads(text[s : e + 1])
                    except json.JSONDecodeError:
                        pass
        return {"error": "No valid JSON found", "raw": text[:500]}


# ── SINGLETON ─────────────────────────────────────────────
_agent: AriaAgent | None = None


def get_agent() -> AriaAgent:
    global _agent
    if _agent is None:
        _agent = AriaAgent()
    return _agent