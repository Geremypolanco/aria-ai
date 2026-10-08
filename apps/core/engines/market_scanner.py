import logging
from typing import Any

from apps.core.tools.ai_client import AIModel, get_ai_client
from apps.core.tools.web_tools import WebTools

logger = logging.getLogger("aria.market_scanner")


class MarketScanner:
    """
    Market Scanning Engine.
    Searches for real economic opportunities in the market.
    """

    def __init__(self):
        self.web = WebTools()
        self.ai = get_ai_client()

    async def scan_opportunities(self) -> list[dict[str, Any]]:
        """Scans the market and returns opportunities sorted by potential ROI."""
        opportunities = []

        # 1. Search for trends on Google Trends
        trends = await self._scan_google_trends()
        opportunities.extend(trends)

        # 2. Search for high-value products on Shopify
        shopify_opps = await self._scan_shopify_opportunities()
        opportunities.extend(shopify_opps)

        # 3. Search for high-engagement LinkedIn niches
        linkedin_opps = await self._scan_linkedin_niches()
        opportunities.extend(linkedin_opps)

        # Sort by expected ROI
        opportunities.sort(key=lambda x: x.get("expected_roi", 0), reverse=True)
        return opportunities

    async def _scan_google_trends(self) -> list[dict[str, Any]]:
        """Searches for emerging trends on Google."""
        query = "trending topics 2026 high demand products"
        results = await self.web.search_web(query, num_results=5)

        if not results.get("success"):
            return []

        # U5 provenance: every opportunity shown to the operator must carry
        # citations derived from the REAL web-search evidence below — an
        # opportunity without provenance is never shown.
        from apps.core.llm.contracts import (
            MarketOpportunityList,
            finding_citations,
            validate_citations,
        )

        web_results = results.get("results") or []
        evidence = [
            {
                "source": f"web:{str(r.get('source', 'search')).lower().replace(' ', '-')}-{i}",
                "title": r.get("title", ""),
                "url": r.get("url", ""),
            }
            for i, r in enumerate(web_results)
            if isinstance(r, dict)
        ]
        citations = finding_citations(evidence)
        if not citations:
            logger.warning("[MarketScanner] no citable evidence — no opportunities (U5)")
            return []

        # Analyze trends with AI
        analysis = await self.ai.complete_json(
            system="You are a market analyst. Identify sales opportunities.",
            user=(
                f"Analyze these trends: {web_results}. Respond with JSON: "
                '{"opportunities": [{topic, market_size, competition_level, '
                "expected_roi (0-10), citations}]}. "
                "Each opportunity's citations MUST be chosen ONLY from this "
                f"evidence list: {citations}. Never invent a citation."
            ),
            model=AIModel.STRATEGY,
            schema=MarketOpportunityList,
            schema_name="MarketOpportunityList",
            agent_name="market_scanner",
        )
        opps = analysis.get("opportunities", []) if isinstance(analysis, dict) else []

        # Keep only citations that actually come from the evidence set; drop
        # opportunities left without provenance instead of showing them.
        valid = set(citations)
        kept: list[dict] = []
        for opp in opps:
            if not isinstance(opp, dict):
                continue
            opp_cites = [c for c in (opp.get("citations") or []) if c in valid]
            if not opp_cites:
                logger.warning(
                    "[MarketScanner] dropping opportunity without provenance: %s",
                    opp.get("topic"),
                )
                continue
            opp["citations"] = opp_cites
            kept.append(opp)
        validate_citations(kept, min_citations=1)
        return kept

    async def _scan_shopify_opportunities(self) -> list[dict[str, Any]]:
        """Searches for high-value Shopify products Aria can replicate."""
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
        """Searches for high-engagement niches on LinkedIn."""
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
