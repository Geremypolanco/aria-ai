"""
Marketing Agent — SEO, viral content, campaigns, and brand growth.

Handles: SEO research, blog posts, social media calendar, email campaigns,
        ad copy, keyword analysis, competitor analysis, content strategy.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from apps.core.agents.base_agent import BaseAgent

logger = logging.getLogger("aria.business.marketing")


class MarketingAgent(BaseAgent):
    IDENTITY = (
        "You are ARIA AI's Marketing Agent. You are a digital CMO expert in growth hacking, "
        "SEO, content marketing, and viral loops. Your goal: maximum reach and conversion. "
        "You generate and execute real campaigns, not just plans."
    )

    def __init__(self) -> None:
        super().__init__(
            name="marketing",
            description="SEO, viral content, email campaigns, social media, and brand growth",
            capabilities=[
                "seo",
                "content_creation",
                "social_media",
                "email_campaigns",
                "competitor_analysis",
                "keyword_research",
                "growth_hacking",
            ],
        )

    async def _execute(self, context: dict[str, Any]) -> dict[str, Any]:
        mission = context.get("mission", "Create a complete marketing strategy")
        niche = context.get("niche", "AI tools")
        context.get("budget", "bootstrap")
        channels = context.get("channels", ["social", "seo", "email"])

        results: dict[str, Any] = {"success": True, "agent": "marketing", "mission": mission}

        tasks_to_run = []

        if "seo" in channels:
            tasks_to_run.append(("seo_strategy", self._create_seo_strategy(niche, mission)))
        if "social" in channels:
            tasks_to_run.append(("social_content", self._create_social_content(niche, mission)))
        if "email" in channels:
            tasks_to_run.append(("email_campaign", self._create_email_campaign(niche, mission)))
        if "content" in channels:
            tasks_to_run.append(("blog_articles", self._create_blog_strategy(niche)))

        task_results = await asyncio.gather(
            *[coro for _, coro in tasks_to_run], return_exceptions=True
        )
        for (key, _), result in zip(tasks_to_run, task_results, strict=False):
            results[key] = result if not isinstance(result, Exception) else {"error": str(result)}

        # Publish content if configured
        if context.get("auto_publish") and results.get("social_content"):
            pub_result = await self._publish_social(results["social_content"])
            results["published"] = pub_result

        results["summary"] = f"Marketing strategy generated for '{niche}'. Channels: {channels}"
        return results

    async def _create_seo_strategy(self, niche: str, mission: str) -> dict:
        strategy = await self.think(
            system=self.IDENTITY,
            user=(
                f"Niche: {niche}\nMission: {mission}\n\n"
                f"Generate: 10 high-intent keywords, 5 SEO article titles, "
                f"meta descriptions, site structure, and backlink strategy. "
                f"Structured format."
            ),
        )
        return {"strategy": strategy, "type": "seo"}

    async def _create_social_content(self, niche: str, mission: str) -> dict:
        """Generates content for all major platforms."""
        from apps.core.tools.social_engine import SocialContentEngine

        engine = SocialContentEngine()
        topic = f"{mission} — {niche}"
        pack = await engine.create_content_pack(
            topic=topic,
            platforms=["instagram", "linkedin", "twitter", "tiktok", "facebook"],
            tone="professional",
        )
        return pack

    async def _create_email_campaign(self, niche: str, mission: str) -> dict:
        campaign = await self.think(
            system=self.IDENTITY,
            user=(
                f"Create a 5-email nurturing sequence campaign for the '{niche}' niche. "
                f"Goal: {mission}. Include: subject, preview text, body (200 words), CTA. "
                f"JSON array format."
            ),
        )
        return {"campaign_sequence": campaign, "emails": 5}

    async def _create_blog_strategy(self, niche: str) -> dict:
        strategy = await self.think(
            system=self.IDENTITY,
            user=(
                f"Niche: {niche}\n"
                f"Generate 10 blog article ideas with: title (SEO-optimized), "
                f"50-word intro, 5-section outline, target keywords. "
                f"Ordered by traffic potential."
            ),
        )
        return {"blog_ideas": strategy}

    async def _publish_social(self, social_content: dict) -> dict:
        """Publishes generated content on active social media."""
        from apps.core.tools.social_engine import SocialContentTools

        poster = SocialContentTools()
        published = {}
        for platform, content in social_content.get("platforms", {}).items():
            if not content.get("success"):
                continue
            text = content.get("content", "")[:500]
            try:
                if platform == "twitter":
                    published[platform] = await poster.post_twitter(text[:280])
                elif platform == "discord":
                    published[platform] = await poster.post_discord_webhook("ARIA Content", text)
                else:
                    published[platform] = {"skipped": True, "reason": "requires OAuth"}
            except Exception as exc:
                published[platform] = {"error": str(exc)}
        return published
