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
                "investor_research",
                "outreach",
                "pitch_decks",
                "linkedin_networking",
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

        # 3. Ejecutar Outreach si está activado — SIEMPRE requiere aprobación
        # humana explícita: _research_investors() no es investigación en
        # tiempo real (ver su docstring), así que un outreach automático
        # enviaría mensajes personalizados dirigidos a firmas reales
        # (Sequoia, Y Combinator, etc.) redactados a partir de una lista
        # fija de ejemplo, no de verificación real. Nunca se auto-aprueba
        # sin importar `auto_outreach` — el dueño debe confirmar por Telegram.
        if context.get("auto_outreach", False):
            approval = await self.request_human_approval(
                action="Enviar outreach de inversión en LinkedIn",
                details=(
                    f"Pitches listos para: {', '.join(p['investor'] for p in pitches)}. "
                    "Nota: la lista de inversores es un ejemplo de referencia, no "
                    "investigación verificada — revisar contenido antes de aprobar."
                ),
            )
            if approval.get("success") and approval.get("status") != "pending":
                outreach_results = await self._execute_outreach(pitches)
                results["outreach_results"] = outreach_results
            else:
                results["outreach_results"] = approval

        results["summary"] = (
            f"Encontrados {len(investors)} inversionistas potenciales. Campaña de outreach lista."
        )
        return results

    async def _research_investors(self, niche: str) -> list[dict]:
        """Placeholder de ejemplo — NO es investigación real ni verificada.

        Antes esto se devolvía como si fuera el resultado de una búsqueda,
        con nombres de firmas reales (Sequoia, Y Combinator...), y se usaba
        para generar pitches personalizados dirigidos a esas firmas por
        nombre. _execute() ahora bloquea cualquier outreach real detrás de
        aprobación humana explícita precisamente porque estos datos no son
        investigación verificada — ver la nota en request_human_approval().
        """
        # En una ejecución real, esto llamaría a AriaMind.execute_tool("web_search", ...)
        return [
            {
                "name": "TechStars AI",
                "type": "Accelerator",
                "focus": "AI/ML",
                "verified": False,
            },
            {
                "name": "Y Combinator",
                "type": "Accelerator",
                "focus": "General Tech",
                "verified": False,
            },
            {
                "name": "Sequoia Capital",
                "type": "VC",
                "focus": "High Growth",
                "verified": False,
            },
            {
                "name": "AngelList AI Syndicate",
                "type": "Angel Group",
                "focus": "Early Stage AI",
                "verified": False,
            },
        ]

    async def _generate_pitches(self, investors: list[dict], amount: str) -> list[dict]:
        pitches = []
        for inv in investors:
            pitch = await self.think(
                system=self.IDENTITY,
                user=f"Redacta un mensaje de LinkedIn personalizado para {inv['name']} ({inv['type']}). "
                f"Estamos buscando {amount} para escalar Aria AI, una IA autónoma enfocada en generar "
                f"revenue en Shopify. No inventes cifras de tracción, clientes o ingresos específicos — "
                f"si no tienes datos verificados a mano, habla del producto y la visión sin afirmar "
                f"métricas concretas no confirmadas.",
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
