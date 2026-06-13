"""
deep_think.py — Razonamiento extendido para ARIA AI.

Inspirado en Claude 3.7 Sonnet "Hybrid Reasoning":
  - Modo estándar: respuesta rápida sin pensamiento visible
  - Modo thinking: pensamiento paso a paso con presupuesto de tokens (hasta 128K)
  - Modo ultra: máximo presupuesto, para problemas de alta complejidad

ARIA usa deep_think para:
  - Análisis estratégico complejo
  - Debugging de problemas difíciles
  - Decisiones de negocio con múltiples variables
  - Investigación que requiere síntesis profunda
  - Planificación de proyectos grandes
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger("aria.deep_think")


@dataclass
class ThinkingResult:
    answer: str
    thinking_trace: Optional[str]
    thinking_tokens: int
    total_tokens: int
    duration_ms: int
    model_used: str
    depth: str  # fast | standard | deep | ultra

    def to_dict(self) -> dict:
        return {
            "answer": self.answer,
            "thinking_tokens": self.thinking_tokens,
            "total_tokens": self.total_tokens,
            "duration_ms": self.duration_ms,
            "model": self.model_used,
            "depth": self.depth,
            "has_trace": bool(self.thinking_trace),
        }


class DeepThink:
    """
    Motor de razonamiento extendido para ARIA.
    Selecciona automáticamente el nivel de pensamiento según la complejidad detectada.
    """

    # Presupuestos de tokens de pensamiento (similar a Claude 3.7)
    BUDGETS = {
        "fast":     0,      # Sin pensamiento explícito
        "standard": 2000,   # Pensamiento breve
        "deep":     8000,   # Pensamiento profundo
        "ultra":    32000,  # Máximo razonamiento
    }

    # Keywords que indican que se necesita pensamiento profundo
    DEEP_TRIGGERS = [
        "estrategia", "strategy", "analiza", "analyze", "evalúa", "evaluate",
        "decide", "decisión", "decision", "complejo", "complex", "optimiza",
        "optimize", "diseña arquitectura", "arquitectura", "architecture",
        "por qué", "why", "cómo debería", "how should", "mejor forma",
        "trade-off", "trade off", "compara", "compare", "prioriza",
        "planifica", "roadmap", "debug difícil", "razona", "think through",
        "investiga a fondo", "analiza en profundidad", "deep dive",
    ]

    async def think(
        self,
        question: str,
        context: str = "",
        depth: str = "auto",
        system: str = "",
        show_trace: bool = False,
    ) -> ThinkingResult:
        """
        Razona sobre una pregunta con el nivel de profundidad adecuado.

        depth: "auto" detecta automáticamente, "fast"|"standard"|"deep"|"ultra" fuerza nivel.
        show_trace: incluye el proceso de razonamiento en la respuesta.
        """
        t0 = time.monotonic()

        if depth == "auto":
            depth = self._detect_depth(question)

        budget = self.BUDGETS.get(depth, 0)

        from apps.core.tools.ai_client import get_ai_client, AIModel
        client = get_ai_client()

        sys_prompt = system or (
            "Eres ARIA, una IA de negocio autónoma con capacidades de razonamiento avanzado. "
            "Piensas de forma estructurada: primero entiendes el problema, consideras múltiples ángulos, "
            "evalúas trade-offs, y luego formulas una respuesta completa y accionable. "
            "Eres directa, honesta y evitas respuestas genéricas."
        )

        full_prompt = question
        if context:
            full_prompt = f"Contexto:\n{context}\n\nPregunta: {question}"

        if budget > 0:
            # Extended thinking: prepend thinking instruction
            thinking_instruction = (
                f"\n\n<thinking_mode>Usa razonamiento paso a paso antes de responder. "
                f"Piensa en voz alta sobre: el problema central, consideraciones clave, "
                f"posibles enfoques, trade-offs, y tu conclusión final. "
                f"Máximo {budget} tokens de pensamiento.</thinking_mode>"
            )
            full_prompt = full_prompt + thinking_instruction
            model = AIModel.STRATEGY
        else:
            model = AIModel.FAST

        response = await client.complete(
            model=model,
            system=sys_prompt,
            user=full_prompt,
            max_tokens=min(4096, budget + 2000) if budget > 0 else 2000,
        )

        duration_ms = int((time.monotonic() - t0) * 1000)

        # Extract thinking trace if present
        thinking_trace = None
        answer         = (response.content if hasattr(response, "content") else str(response)) or ""

        if budget > 0 and "<think>" in answer:
            import re
            trace_m = re.search(r"<think>(.*?)</think>", answer, re.DOTALL)
            if trace_m:
                thinking_trace = trace_m.group(1).strip()
                answer = answer.replace(trace_m.group(0), "").strip()

        # Estimate token counts
        thinking_tokens = len((thinking_trace or "").split()) * 4 // 3
        total_tokens    = len(answer.split()) * 4 // 3 + thinking_tokens

        logger.info(
            "[DeepThink] depth=%s budget=%d duration=%dms ~%d tokens",
            depth, budget, duration_ms, total_tokens
        )

        return ThinkingResult(
            answer=answer,
            thinking_trace=thinking_trace if show_trace else None,
            thinking_tokens=thinking_tokens,
            total_tokens=total_tokens,
            duration_ms=duration_ms,
            model_used=model.value if hasattr(model, "value") else str(model),
            depth=depth,
        )

    async def think_and_plan(
        self, objective: str, context: str = "", constraints: list[str] = None
    ) -> dict[str, Any]:
        """
        Razonamiento estructurado para planificación de proyectos.
        Retorna plan detallado con fases, recursos y riesgos.
        """
        constraints_text = "\n".join(f"- {c}" for c in (constraints or []))
        prompt = (
            f"Objetivo: {objective}\n"
            + (f"Restricciones:\n{constraints_text}\n" if constraints_text else "")
            + "\nCrea un plan de ejecución detallado con:\n"
            "1. Análisis de la situación actual\n"
            "2. Fases de implementación (con duración estimada)\n"
            "3. Recursos necesarios\n"
            "4. Riesgos y mitigaciones\n"
            "5. KPIs de éxito\n"
            "6. Próximos 3 pasos inmediatos\n"
        )

        result = await self.think(prompt, context=context, depth="deep")
        return {
            "plan": result.answer,
            "thinking_depth": result.depth,
            "duration_ms": result.duration_ms,
        }

    async def analyze_decision(
        self,
        question: str,
        options: list[str],
        criteria: list[str] = None,
    ) -> dict[str, Any]:
        """
        Framework de decisión estructurado con análisis multi-criterio.
        Como un consultor de McKinsey pensando en voz alta.
        """
        options_text  = "\n".join(f"  {i+1}. {o}" for i, o in enumerate(options))
        criteria_text = "\n".join(f"  - {c}" for c in (criteria or ["impacto", "esfuerzo", "riesgo", "costo"]))

        prompt = (
            f"Decisión a tomar: {question}\n\n"
            f"Opciones:\n{options_text}\n\n"
            f"Criterios de evaluación:\n{criteria_text}\n\n"
            "Analiza cada opción frente a los criterios, identifica la mejor decisión "
            "y justifica con razonamiento sólido. Sé directo sobre cuál recomiendas."
        )

        result = await self.think(prompt, depth="deep")
        return {
            "recommendation": result.answer,
            "depth": result.depth,
            "duration_ms": result.duration_ms,
        }

    async def debug_problem(
        self,
        problem: str,
        context: str = "",
        error_trace: str = "",
    ) -> dict[str, Any]:
        """
        Debugging profundo — piensa como un senior engineer con 20 años de experiencia.
        """
        prompt = (
            f"Problema: {problem}\n"
            + (f"Error:\n```\n{error_trace}\n```\n" if error_trace else "")
            + (f"Contexto: {context}\n" if context else "")
            + "\nDiagnostica la causa raíz, explica por qué ocurre, "
            "y proporciona la solución exacta con código si aplica."
        )

        result = await self.think(
            prompt, depth="deep",
            system=(
                "Eres un senior engineer con 20 años de experiencia. "
                "Diagnosticas problemas de forma metódica: síntomas → causa raíz → solución. "
                "Nunca das respuestas vagas. Siempre proporciones código ejecutable cuando aplica."
            ),
        )
        return {
            "diagnosis": result.answer,
            "depth": result.depth,
            "duration_ms": result.duration_ms,
        }

    def _detect_depth(self, question: str) -> str:
        """Detecta automáticamente el nivel de pensamiento necesario."""
        q_lower = question.lower()
        word_count = len(question.split())

        # Preguntas muy largas o complejas → deep
        if word_count > 50:
            return "deep"

        # Keywords de alta complejidad → deep
        deep_count = sum(1 for kw in self.DEEP_TRIGGERS if kw in q_lower)
        if deep_count >= 2:
            return "deep"
        if deep_count == 1:
            return "standard"

        # Preguntas cortas y simples → fast
        return "fast"


# ══════════════════════════════════════════════════════════════
# PROGRESS STREAMING — Manus-style progress updates
# ══════════════════════════════════════════════════════════════

class ProgressStream:
    """
    Transmite actualizaciones de progreso en tiempo real durante tareas largas.
    Inspirado en Manus `message` tool — updates del agente al usuario.
    """

    def __init__(self, session_id: str, task_name: str) -> None:
        self.session_id = session_id
        self.task_name  = task_name
        self._steps: list[dict] = []

    async def update(self, step: str, detail: str = "", icon: str = "⚡") -> None:
        """Envía actualización de progreso al usuario."""
        entry = {"step": step, "detail": detail, "icon": icon}
        self._steps.append(entry)
        logger.info("[Progress:%s] %s %s", self.task_name, icon, step)

        # Enviar a Telegram si la sesión es de Telegram
        if self.session_id.startswith("telegram:"):
            chat_id = self.session_id.replace("telegram:", "")
            if chat_id.isdigit():
                try:
                    from apps.core.tools.telegram_bot import get_bot
                    msg = f"{icon} **{step}**" + (f"\n_{detail}_" if detail else "")
                    await get_bot()._send_message(int(chat_id), msg)
                except Exception:
                    pass

        # Push to WebSocket activity log
        try:
            from apps.core.routes.api import _log_activity
            _log_activity("INFO", f"[{self.task_name}] {step}", category="progress")
        except Exception:
            pass

    async def complete(self, message: str = "") -> None:
        await self.update(message or f"{self.task_name} completado", icon="✅")

    async def error(self, message: str) -> None:
        await self.update(f"Error: {message}", icon="❌")

    def get_steps(self) -> list[dict]:
        return list(self._steps)


# Singleton
_deep_think: Optional[DeepThink] = None


def get_deep_think() -> DeepThink:
    global _deep_think
    if _deep_think is None:
        _deep_think = DeepThink()
    return _deep_think
