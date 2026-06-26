"""
Investor Agent — Búsqueda de capital, outreach a VCs/Angels y pitch decks.
"""
from __future__ import annotations
import logging
from typing import Any
from apps.core.agents.base_agent import BaseAgent

logger = logging.getLogger("aria.business.investor")

class InvestorAgent(BaseAgent):
    IDENTITY = (
        "Eres el Investor Agent de ARIA AI. Tu misión es asegurar capital real para el proyecto. "
        "Identificas inversionistas ángeles, VCs y socios estratégicos. Redactas pitches "
        "irresistibles y ejecutas campañas de outreach en LinkedIn y email. "
        "No pides permiso, buscas dinero real. Eres agresivo, directo y enfocado en resultados. "
        "Garantizas que el valor de Aria sea evidente para cualquier inversor serio."
    )

    def __init__(self) -> None:
        super().__init__(
            name="investor",
            description="Búsqueda de capital, outreach a inversores, pitch decks y gestión de equity",
            capabilities=[
                "investor_research", "outreach", "pitch_decks", "linkedin_networking",
            ],
        )

    async def _execute(self, context: dict[str, Any]) -> dict[str, Any]:
        mission = context.get("mission", "Buscar inversionistas para Aria AI")
        niche = context.get("niche", "AI SaaS / E-commerce")
        target_amount = context.get("target_amount", "$100k - $500k")

        results: dict[str, Any] = {"success": True, "agent": "investor", "mission": mission}

        # 1. Investigar inversionistas potenciales
        investors = await self._research_investors(niche)
        results["potential_investors"] = investors

        # 2. Generar Pitch y Outreach
        pitches = await self._generate_pitches(investors, target_amount)
        results["outreach_campaign"] = pitches

        # 3. Ejecutar Outreach si está activado
        if context.get("auto_outreach", False):
            outreach_results = await self._execute_outreach(pitches)
            results["outreach_results"] = outreach_results

        results["summary"] = f"Encontrados {len(investors)} inversionistas potenciales. Campaña de outreach lista."
        return results

    async def _research_investors(self, niche: str) -> list[dict]:
        """Simulación de búsqueda profunda de inversores (usaría web_search en producción)."""
        # En una ejecución real, esto llamaría a AriaMind.execute_tool("web_search", ...)
        return [
            {"name": "TechStars AI", "type": "Accelerator", "focus": "AI/ML"},
            {"name": "Y Combinator", "type": "Accelerator", "focus": "General Tech"},
            {"name": "Sequoia Capital", "type": "VC", "focus": "High Growth"},
            {"name": "AngelList AI Syndicate", "type": "Angel Group", "focus": "Early Stage AI"}
        ]

    async def _generate_pitches(self, investors: list[dict], amount: str) -> list[dict]:
        pitches = []
        for inv in investors:
            pitch = await self.think(
                system=self.IDENTITY,
                user=f"Redacta un mensaje de LinkedIn personalizado para {inv['name']} ({inv['type']}). "
                     f"Estamos buscando {amount} para escalar Aria AI, una IA autónoma que genera revenue real en Shopify. "
                     f"Enfócate en tracción real y ROI inmediato."
            )
            pitches.append({"investor": inv["name"], "pitch": pitch})
        return pitches

    async def _execute_outreach(self, pitches: list[dict]) -> dict:
        """Ejecuta el posteo en LinkedIn o envío de mensajes."""
        from apps.core.tools.social_media import SocialMediaManager
        sm = SocialMediaManager()
        results = []
        for p in pitches:
            # Enviar como post o mensaje privado si la API lo permite
            res = await sm.post_content("linkedin", p["pitch"])
            results.append({"investor": p["investor"], "status": res})
        return {"sent_count": len(results), "details": results}
