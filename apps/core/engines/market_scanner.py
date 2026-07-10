import logging
from typing import Any

from apps.core.tools.ai_client import AIModel, get_ai_client
from apps.core.tools.web_tools import WebTools

logger = logging.getLogger("aria.market_scanner")


class MarketScanner:
    """
    Motor de Escaneo de Mercado.
    Busca oportunidades económicas reales en el mercado.
    """

    def __init__(self):
        self.web = WebTools()
        self.ai = get_ai_client()

    async def scan_opportunities(self) -> list[dict[str, Any]]:
        """Escanea el mercado y retorna oportunidades ordenadas por ROI potencial."""
        opportunities = []

        # 1. Buscar tendencias en Google Trends
        trends = await self._scan_google_trends()
        opportunities.extend(trends)

        # 2. Buscar productos de alto valor en Shopify
        shopify_opps = await self._scan_shopify_opportunities()
        opportunities.extend(shopify_opps)

        # 3. Buscar nichos de LinkedIn con alto engagement
        linkedin_opps = await self._scan_linkedin_niches()
        opportunities.extend(linkedin_opps)

        # Ordenar por ROI esperado
        opportunities.sort(key=lambda x: x.get("expected_roi", 0), reverse=True)
        return opportunities

    async def _scan_google_trends(self) -> list[dict[str, Any]]:
        """Busca tendencias emergentes en Google."""
        query = "trending topics 2026 high demand products"
        results = await self.web.search_web(query, num_results=5)

        if not results.get("success"):
            return []

        # Analizar tendencias con IA
        analysis = await self.ai.complete_json(
            system="Eres un analista de mercado. Identifica oportunidades de venta.",
            user=f"Analiza estas tendencias: {results.get('results')}. Responde con lista de oportunidades: [{{topic, market_size, competition_level, expected_roi}}]",
            model=AIModel.STRATEGY,
        )

        return analysis if isinstance(analysis, list) else []

    async def _scan_shopify_opportunities(self) -> list[dict[str, Any]]:
        """Busca productos de alto valor en Shopify que Aria pueda replicar."""
        query = "best selling digital products shopify 2026 high ticket"
        results = await self.web.search_web(query, num_results=5)

        if not results.get("success"):
            return []

        return [
            {
                "source": "shopify",
                "opportunity": r.get("title", ""),
                "market_size": "medium",
                "expected_roi": 5.0,
                "action": "analyze_and_replicate",
            }
            for r in results.get("results", [])[:3]
        ]

    async def _scan_linkedin_niches(self) -> list[dict[str, Any]]:
        """Busca nichos de alto engagement en LinkedIn."""
        query = "top performing LinkedIn content 2026 engagement rate"
        results = await self.web.search_web(query, num_results=5)

        if not results.get("success"):
            return []

        return [
            {
                "source": "linkedin",
                "niche": r.get("title", ""),
                "engagement_potential": "high",
                "expected_roi": 4.0,
                "action": "create_viral_content",
            }
            for r in results.get("results", [])[:3]
        ]
