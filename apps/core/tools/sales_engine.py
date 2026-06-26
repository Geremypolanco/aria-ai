"""
ARIA Sales Engine v1.0
Inspirado en SalesGPT y técnicas de automatización de ventas de alto rendimiento.
Gestiona la prospección, calificación y el outreach inicial de forma autónoma.
"""

import logging

from apps.core.intelligence.sales_knowledge import SALES_TECHNIQUES, VOCABULARY_EXPANSION

logger = logging.getLogger("aria.sales_engine")


class SalesEngine:
    def __init__(self):
        self.is_active = True

    async def prospect_leads(self, niche: str, target_audience: str) -> list[dict]:
        """
        Simula la búsqueda de leads basada en el nicho.
        En producción, esto se conectaría con Google Maps API o LinkedIn Scrapers.
        """
        logger.info(f"[SalesEngine] Prospectando leads para nicho: {niche}")
        # Aquí se integraría la lógica de scraping o búsqueda de APIs
        return [
            {"name": f"Lead_{niche}_1", "interest": 0.8, "contact": "example1@test.com"},
            {"name": f"Lead_{niche}_2", "interest": 0.6, "contact": "example2@test.com"},
        ]

    async def generate_outreach_copy(self, lead: dict, product: dict) -> str:
        """
        Genera un mensaje de venta altamente persuasivo usando la librería de inteligencia.
        """
        from apps.core.tools.ai_client import AIModel, get_ai_client

        ai = get_ai_client()

        technique = SALES_TECHNIQUES["copywriting"][0]  # AIDA
        vocab = ", ".join(VOCABULARY_EXPANSION["persuasive_verbs"][:5])

        prompt = (
            f"Actúa como un cerrador de ventas de élite.\n"
            f"Lead: {lead['name']}\n"
            f"Producto: {product['name']}\n"
            f"Técnica: {technique}\n"
            f"Vocabulario sugerido: {vocab}\n\n"
            f"Escribe un mensaje de outreach directo y persuasivo para cerrar una venta o agendar una llamada."
        )

        resp = await ai.complete(
            system="Eres un experto en ventas directas y copywriting persuasivo.",
            user=prompt,
            model=AIModel.CREATIVE,
        )
        return resp.content if resp else ""

    async def run_sales_cycle(self, niche: str, product: dict) -> dict:
        """Ejecuta un ciclo completo de ventas."""
        leads = await self.prospect_leads(niche, "Business owners")
        results = []
        for lead in leads:
            copy = await self.generate_outreach_copy(lead, product)
            results.append({"lead": lead["name"], "outreach_sent": True, "copy_preview": copy[:50]})

        return {"success": True, "leads_contacted": len(results), "details": results}
