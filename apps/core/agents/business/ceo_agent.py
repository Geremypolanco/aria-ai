"""
CEO Agent — Estrategia, decisiones de alto nivel y delegación a agentes especializados.

El CEO Agent orquesta los demás agentes, prioriza iniciativas de negocio,
analiza métricas globales, y toma decisiones ejecutivas autónomas.
"""

from __future__ import annotations

import logging
from typing import Any

from apps.core.agents.base_agent import BaseAgent

logger = logging.getLogger("aria.business.ceo")


class CEOAgent(BaseAgent):
    IDENTITY = (
        "Eres el CEO Agent de ARIA AI. Piensas estratégicamente como un CEO de Silicon Valley. "
        "Tu objetivo: maximizar revenue, crecer la marca, y mantener operaciones autónomas. "
        "Delega tareas a agentes especializados. Toma decisiones basadas en datos reales."
    )

    def __init__(self) -> None:
        super().__init__(
            name="ceo",
            description="Estrategia ejecutiva, decisiones de alto nivel, delegación y coordinación de negocio",
            capabilities=["strategy", "planning", "delegation", "metrics", "decisions", "growth"],
        )

    async def _execute(self, context: dict[str, Any]) -> dict[str, Any]:
        mission = context.get("mission", "Analizar estado del negocio y proponer plan de acción")
        data = context.get("data", {})
        timeframe = context.get("timeframe", "próximas 2 semanas")

        # Recopilar métricas actuales
        metrics = await self._gather_business_metrics()

        # Análisis estratégico con IA
        plan = await self.think(
            system=self.IDENTITY,
            user=(
                f"Misión: {mission}\n"
                f"Datos adicionales: {data}\n"
                f"Timeframe: {timeframe}\n"
                f"Métricas actuales: {metrics}\n\n"
                f"Genera un plan ejecutivo con: "
                f"1) Situación actual 2) 3 prioridades inmediatas 3) KPIs a trackear "
                f"4) Delegación a agentes específicos 5) Próximos pasos concretos."
            ),
        )

        # Identificar qué agentes activar
        agents_to_activate = self._identify_required_agents(plan, mission)

        return {
            "success": True,
            "agent": "ceo",
            "mission": mission,
            "strategic_plan": plan,
            "agents_to_activate": agents_to_activate,
            "metrics_snapshot": metrics,
            "summary": plan[:400] if plan else "Plan generado",
        }

    async def _gather_business_metrics(self) -> dict:
        """Reúne métricas reales del negocio desde múltiples fuentes."""
        metrics: dict = {}
        try:
            from apps.core.training.continuous_trainer import get_trainer

            status = get_trainer().get_status()
            metrics["system_cycle"] = status.get("cycle", 0)
            metrics["skills"] = status.get("skill_scores", {})
        except Exception:
            pass
        return metrics

    def _identify_required_agents(self, plan: str, mission: str) -> list[str]:
        """Identifica qué agentes especializados se necesitan activar."""
        plan_lower = (plan + mission).lower()
        agents = []
        if any(w in plan_lower for w in ["market", "seo", "content", "blog", "social"]):
            agents.append("marketing")
        if any(w in plan_lower for w in ["revenue", "sale", "stripe", "shopify", "product"]):
            agents.append("sales")
        if any(w in plan_lower for w in ["code", "deploy", "bug", "feature", "api", "app"]):
            agents.append("developer")
        if any(w in plan_lower for w in ["research", "analys", "trend", "competitor"]):
            agents.append("research")
        if any(w in plan_lower for w in ["email", "newsletter", "publish", "article"]):
            agents.append("content")
        if any(w in plan_lower for w in ["finance", "cost", "profit", "revenue", "expense"]):
            agents.append("finance")
        return agents or ["research"]
