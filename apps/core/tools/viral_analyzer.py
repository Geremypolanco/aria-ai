import logging
from typing import Any

from apps.core.tools.ai_client import AIModel, get_ai_client
from apps.core.tools.web_tools import WebTools

logger = logging.getLogger("aria.viral")


class ViralAnalyzer:
    """
    Virality and content-mimicry analyzer.
    Searches for successful posts and extracts their structural patterns.
    """

    def __init__(self):
        self.web = WebTools()
        self.ai = get_ai_client()

    async def analyze_trending_formats(
        self, niche: str, platform: str = "linkedin"
    ) -> dict[str, Any]:
        """Searches for viral posts in a niche and extracts their structural DNA."""
        query = f"top viral {niche} posts on {platform} 2026 examples"
        search_results = await self.web.search_web(query, num_results=5)

        if not search_results.get("success"):
            return {"success": False, "error": "Could not obtain search results"}

        # Analyze the snippets and titles to extract patterns
        analysis_prompt = f"""
        Analyze these search results about viral posts on {platform} for the niche '{niche}':
        {search_results.get('results')}

        EXTRACT THE VIRAL DNA:
        1. Hook: How do the most successful posts open?
        2. Structure: Do they use lists, storytelling, data, or questions?
        3. Visual format: Do they mention images, infographics, or videos?
        4. Call to action (CTA): How do they close?

        Generate a MASTER TEMPLATE that ARIA can use to replicate this success.
        Respond in JSON with: hook_style, body_structure, visual_recommendation, cta_style, example_template.
        """

        analysis = await self.ai.complete_json(
            system="You are an expert in Growth Hacking and Digital Virality.",
            user=analysis_prompt,
            model=AIModel.STRATEGY,
        )

        return {"success": True, "platform": platform, "niche": niche, "viral_dna": analysis}

    async def find_high_value_digital_products(self, category: str) -> list[dict[str, Any]]:
        """Searches for high-value digital products that are trending."""
        query = f"best selling high ticket digital products {category} shopify 2026"
        search_results = await self.web.search_web(query, num_results=5)
        return search_results.get("results", [])
