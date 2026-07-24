"""
MarketingAgent — Creates and distributes automated content.
Uses: Buffer (social media), Mailchimp (email), Google Trends (trends),
     Pexels (images), ElevenLabs (voice), Canva (design), Cloudinary (CDN).
"""

from __future__ import annotations

import logging
from typing import Any

from apps.core.agents.base_agent import BaseAgent
from apps.core.tools.ai_client import AIModel

logger = logging.getLogger("aria.marketing_agent")


class MarketingAgent(BaseAgent):
    def __init__(self) -> None:
        super().__init__(
            name="marketing",
            description="Marketing and social media — automated content",
            capabilities=[
                "content_creation",
                "social_posting",
                "email_campaigns",
                "trend_analysis",
                "image_generation",
                "seo_content",
            ],
        )

    async def _execute(self, context: dict[str, Any]) -> dict[str, Any]:
        task = context.get("task", "")
        niche = context.get("niche", "digital products")
        language = context.get("language", "es")
        product = context.get("product", {})

        results: dict[str, Any] = {"success": True, "agent": "marketing_agent"}

        # Get trending topics
        trends = await self._get_trending_topics(niche)
        results["trends"] = trends

        # Create content pack with AI
        content_pack = await self._create_content_pack(niche, language, trends, product, task)
        results["content_pack"] = content_pack

        # Publish to social media via Buffer
        if content_pack.get("social_posts"):
            social_result = await self._publish_social_posts(content_pack["social_posts"])
            results["social_posting"] = social_result

        # Create an email campaign if there's a product
        if product and product.get("name"):
            email_result = await self._send_email_campaign(product, content_pack, language)
            results["email_campaign"] = email_result

        # Save to Supabase
        await self._save_campaign(niche, content_pack, results)

        await self._log(
            "marketing_executed",
            f"Nicho: {niche} | Posts: {len(content_pack.get('social_posts', []))}",
        )
        return results

    async def _get_trending_topics(self, niche: str) -> list[str]:
        """Gets trending topics from Google Trends and NewsAPI."""
        trends = []
        try:
            from apps.core.tools.google_tools import GoogleTools

            google = GoogleTools()
            trending = await google.get_trending_searches(geo="US")
            if trending.get("success"):
                trends = [t["topic"] for t in trending.get("trends", [])[:5]]
        except Exception as exc:
            logger.warning("[MarketingAgent] Google Trends error: %s", exc)

        try:
            from apps.core.tools.market_tools import MarketTools

            market = MarketTools()
            news = await market.fetch_niche_news(niche)
            if news:
                trends.extend(news[:3])
        except Exception as exc:
            logger.warning("[MarketingAgent] NewsAPI error: %s", exc)

        return trends[:8]

    async def _create_content_pack(
        self, niche: str, language: str, trends: list[str], product: dict, task: str
    ) -> dict[str, Any]:
        """Generates a complete content pack with AI."""
        product_name = product.get("name", "")
        product_url = product.get("url", "")

        prompt = (
            f"You are a digital marketing expert for digital products.\n"
            f"Niche: {niche}\n"
            f"Target language: {language}\n"
            f"Trending topics: {', '.join(trends[:5])}\n"
            f"Product to promote: {product_name or 'no specific product'}\n"
            f"Product URL: {product_url}\n"
            f"Additional task: {task}\n\n"
            "Generate a complete content pack in JSON with:\n"
            "{\n"
            '  "social_posts": [\n'
            '    {"platform": "twitter", "text": "280-char tweet with hashtags"},\n'
            '    {"platform": "linkedin", "text": "500-char professional post"},\n'
            '    {"platform": "instagram", "text": "caption with emojis and hashtags"}\n'
            "  ],\n"
            '  "email_subject": "Email subject line",\n'
            '  "email_body": "Email body in basic HTML",\n'
            '  "blog_title": "SEO blog article title",\n'
            '  "blog_intro": "Article intro paragraph (300 words)",\n'
            '  "seo_keywords": ["keyword1", "keyword2", "keyword3"],\n'
            '  "cta": "Main call to action"\n'
            "}"
        )

        content_json = await self.think(
            system="You are an expert digital marketing copywriter. Respond ONLY with valid JSON.",
            user=prompt,
            model=AIModel.CREATIVE,
        )

        try:
            import json
            import re

            match = re.search(r"\{.*\}", content_json or "", re.DOTALL)
            if match:
                return json.loads(match.group())
        except Exception:
            pass

        # Basic fallback
        return {
            "social_posts": [
                {
                    "platform": "twitter",
                    "text": f"🚀 Discover the best in {niche}. #digitalproducts #{niche.replace(' ', '')}",
                },
                {
                    "platform": "linkedin",
                    "text": f"New content about {niche} available. Learn how to monetize this niche.",
                },
            ],
            "email_subject": f"Opportunity in {niche} — Act now",
            "email_body": f"<h2>Opportunity in {niche}</h2><p>We've identified a great opportunity in this market.</p>",
            "blog_title": f"How to monetize {niche} in 2025",
            "blog_intro": f"The {niche} market is booming...",
            "seo_keywords": [niche, "digital products", "monetization"],
            "cta": "Discover it now",
        }

    async def _publish_social_posts(self, posts: list[dict]) -> dict[str, Any]:
        """Publishes posts to social media via Buffer."""
        try:
            from apps.core.tools.buffer_tools import BufferTools

            buffer = BufferTools()
            results = []
            for post in posts:
                text = post.get("text", "")
                if not text:
                    continue
                res = await buffer.post_update(text=text, now=False)
                results.append(
                    {"platform": post.get("platform", "?"), "success": res.get("success", False)}
                )
                logger.info("[MarketingAgent] Buffer post: %s", res)
            return {
                "success": True,
                "posts_queued": len([r for r in results if r["success"]]),
                "results": results,
            }
        except Exception as exc:
            logger.error("[MarketingAgent] Buffer error: %s", exc)
            return {
                "success": False,
                "error": str(exc),
                "note": "BUFFER_TOKEN not configured or API error",
            }

    async def _send_email_campaign(
        self, product: dict, content_pack: dict, language: str
    ) -> dict[str, Any]:
        """Sends an email campaign via Mailchimp."""
        try:
            from apps.core.tools.mailchimp_tools import MailchimpTools

            mailchimp = MailchimpTools()

            # Get the first available list
            lists_res = await mailchimp.get_lists()
            if not lists_res.get("success") or not lists_res.get("lists"):
                return {"success": False, "error": "No Mailchimp lists available"}

            list_id = lists_res["lists"][0]["id"]

            result = await mailchimp.create_campaign(
                list_id=list_id,
                subject=content_pack.get(
                    "email_subject", f"Special offer — {product.get('name', 'Product')}"
                ),
                from_name="ARIA AI",
                reply_to="noreply@aria-ai.com",
                body_html=content_pack.get("email_body", "<p>New product available.</p>"),
                preview_text=content_pack.get("cta", "Act now"),
            )
            return result
        except Exception as exc:
            logger.error("[MarketingAgent] Mailchimp error: %s", exc)
            return {"success": False, "error": str(exc), "note": "Mailchimp not configured"}

    async def _save_campaign(self, niche: str, content_pack: dict, results: dict) -> None:
        """Saves the campaign to Supabase."""
        try:
            from apps.core.memory.supabase_client import get_db

            db = get_db()
            posts = content_pack.get("social_posts", [])
            if posts:
                await db.save_marketing_campaign(
                    name=f"Campaign_{niche}_{int(__import__('time').time())}",
                    platform="multi",
                    type_="social_email",
                    content=posts[0].get("text", "")[:500],
                    target_niche=niche,
                    metadata={"content_pack": content_pack, "results": results},
                )
        except Exception as exc:
            logger.warning("[MarketingAgent] Error saving campaign: %s", exc)
