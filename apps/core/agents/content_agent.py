"""
ARIA Content Agent — Agent specialized in content generation and monetization.

Runs the full pipeline:
1. Detects trends (HN + Reddit + Product Hunt)
2. Generates SEO articles (Groq/HuggingFace)
3. Injects affiliate links (Amazon + ClickBank)
4. Publishes to Medium + Dev.to + Hashnode
5. Distributes on social media
6. Creates digital products on Gumroad
7. Logs everything to Supabase

Runs on every autonomous cycle of the orchestrator.
"""

from __future__ import annotations

import logging
from typing import Any

from apps.core.agents.base_agent import BaseAgent

logger = logging.getLogger("aria.content_agent")


class ContentAgent(BaseAgent):
    """
    Content generation and monetization agent.
    Operates fully autonomously.
    """

    def __init__(self) -> None:
        super().__init__(
            name="content",
            description="Generates and monetizes content automatically",
            capabilities=[
                "trend_detection",
                "article_generation",
                "affiliate_injection",
                "multi_platform_publishing",
                "social_distribution",
                "digital_product_creation",
            ],
        )

    async def _execute(self, context: dict[str, Any]) -> dict[str, Any]:
        """Agent entry point."""
        task = context.get("task", "full_pipeline")
        language = context.get("language", "es")
        num_articles = context.get("num_articles", 3)

        if task == "full_pipeline":
            return await self._run_full_pipeline(language, num_articles)
        if task == "trending_only":
            return await self._get_trends_report()
        if task == "create_product":
            topic = context.get("topic", "artificial intelligence for business")
            category = context.get("category", "business")
            return await self._create_product(topic, category)
        if task == "newsletter":
            return await self._send_newsletter_digest()
        if task == "creative_creation":
            format = context.get("format", "image")
            topic = context.get("topic", "cyberpunk city")
            return await self._run_creative_task(format, topic)
        return await self._run_full_pipeline(language, num_articles)

    async def _run_creative_task(self, format: str, topic: str) -> dict:
        """Runs real multimedia creation tasks."""
        from apps.core.tools.creative_engine import CreativeEngine

        creative = CreativeEngine()

        if format in ["music", "song"]:
            return await creative.generate_music(topic)
        if format in ["video", "clip"]:
            return await creative.generate_video(topic)
        if format in ["manga", "anime"]:
            return await creative.create_manga_page(topic)
        if format in ["software", "app", "game"]:
            return await creative.generate_software_module(topic)
        if format == "landing":
            return await creative.create_landing_page(
                topic, ["AI Powered", "Autonomous", "Revenue Driven"]
            )
        # Default to high-quality image
        from apps.core.tools.content_tools import ContentTools

        ct = ContentTools()
        return await ct.generate_and_upload_image(topic)

    async def _run_full_pipeline(self, language: str = "es", num_articles: int = 3) -> dict:
        """Full pipeline: trends → articles → publishing → distribution."""
        from apps.core.tools.content_pipeline import ContentPipeline

        logger.info(
            "[ContentAgent] Starting full pipeline — %d articles in %s",
            num_articles,
            language,
        )

        pipeline = ContentPipeline()
        result = await pipeline.run_pipeline(num_articles=num_articles, language=language)

        # If the pipeline succeeded, create a digital product on the most popular topic
        if result.get("success") and result.get("articles"):
            top_article = result["articles"][0]
            topic = top_article.get("title", "artificial intelligence")
            category = "tech"  # default

            try:
                product_result = await self._create_product(topic, category)
                result["digital_product"] = product_result
            except Exception as exc:
                logger.warning("[ContentAgent] Error creating digital product: %s", exc)

        # Build summary
        articles_count = result.get("articles_published", 0)
        result["summary"] = f"Pipeline complete: {articles_count} articles published. " + (
            "Digital product created on Gumroad."
            if result.get("digital_product", {}).get("success")
            else ""
        )

        logger.info("[ContentAgent] Pipeline complete — %d articles", articles_count)
        return result

    async def _get_trends_report(self) -> dict:
        """Fetches and reports current trends."""
        from apps.core.tools.content_pipeline import ContentPipeline

        pipeline = ContentPipeline()
        topics = await pipeline.get_trending_topics(limit=15)
        return {
            "success": True,
            "topics": topics,
            "count": len(topics),
            "summary": f"Found {len(topics)} trending topics",
        }

    async def _create_product(self, topic: str, category: str) -> dict:
        """Creates a digital product on Gumroad."""
        from apps.core.tools.affiliate_tools import AffiliateTools

        tools = AffiliateTools()
        result = await tools.auto_create_digital_product(topic, category)
        return result

    # ── HF CAPABILITIES (always available with HF_TOKEN) ────────────────────

    async def _translate_with_hf(self, text: str, source: str = "en", target: str = "es") -> str:
        """Translates text using HuggingFace Helsinki-NLP."""
        try:
            from apps.core.tools.hf_discovery import get_hf

            result = await get_hf().translate(text, source_lang=source, target_lang=target)
            if result.get("success") and result.get("translation"):
                return result["translation"]
        except Exception as exc:
            logger.warning("[ContentAgent] HF translate failed: %s", exc)
        return text  # fallback: original text

    async def _analyze_content_sentiment(self, text: str) -> dict:
        """Analyzes the sentiment of a text with HuggingFace."""
        try:
            from apps.core.tools.hf_discovery import get_hf

            return await get_hf().analyze_sentiment(text[:500])
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    async def _classify_topic(self, text: str, topics: list) -> dict:
        """Classifies the topic of a text with zero-shot classification."""
        try:
            from apps.core.tools.hf_discovery import get_hf

            return await get_hf().classify_text(text[:400], topics)
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    async def _generate_cover_image(self, title: str) -> dict:
        """Generates a cover image for an article using FLUX/SDXL."""
        try:
            from apps.core.tools.hf_discovery import get_hf

            prompt = f"Professional blog cover image for article: {title}. Modern, clean design, tech aesthetic."
            return await get_hf().generate_image(prompt)
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    async def _summarize_for_social(self, article_text: str, max_length: int = 150) -> str:
        """Summarizes a long article for social media posts."""
        try:
            from apps.core.tools.hf_discovery import get_hf

            result = await get_hf().summarize(article_text[:2000], max_length=max_length)
            if result.get("success") and result.get("summary"):
                return result["summary"]
        except Exception as exc:
            logger.warning("[ContentAgent] HF summarize failed: %s", exc)
        return article_text[:max_length]

    async def _extract_article_entities(self, text: str) -> dict:
        """Extracts people, companies, and topics from an article for SEO and targeting."""
        try:
            from apps.core.tools.hf_discovery import get_hf

            return await get_hf().extract_entities(text[:512])
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    async def get_hf_capabilities(self) -> dict:
        """Reports which HF capabilities are available for this agent."""
        try:
            from apps.core.tools.hf_discovery import get_hf

            report = await get_hf().capability_report()
            return {
                "available": report.get("available", False),
                "tasks_count": report.get("tasks_count", 0),
                "content_relevant": [
                    t
                    for t in report.get("supported_tasks", [])
                    if t
                    in [
                        "translation",
                        "summarization",
                        "sentiment-analysis",
                        "image-generation",
                        "text-to-speech",
                        "zero-shot-classification",
                        "named-entity-recognition",
                    ]
                ],
            }
        except Exception as exc:
            return {"available": False, "error": str(exc)}

    async def _send_newsletter_digest(self) -> dict:
        """Sends a digest of the latest published articles."""
        try:
            from apps.core.memory.supabase_client import get_db
            from apps.core.tools.publishing_tools import PublishingTools

            db = get_db()
            publisher = PublishingTools()

            # Fetch latest articles
            result = (
                db._client.table("products")
                .select("*")
                .eq("type", "content_article")
                .order("created_at", desc=True)
                .limit(5)
                .execute()
            )

            articles = result.data or []
            if not articles:
                return {"success": False, "error": "No recent articles"}

            # Build newsletter
            html = "<h1>ARIA Digest — Latest articles</h1>\n<ul>"
            text = "ARIA Digest — Latest articles\n\n"
            for a in articles:
                html += f'<li><a href="{a.get("url", "")}">{a.get("name", "")}</a></li>'
                text += f"- {a.get('name', '')}: {a.get('url', '')}\n"
            html += "</ul>"

            send_result = await publisher.send_newsletter(
                subject="ARIA Digest — New articles published",
                html_content=html,
                plain_text=text,
            )
            return send_result

        except Exception as exc:
            logger.error("[ContentAgent] Newsletter error: %s", exc)
            return {"success": False, "error": str(exc)}
