"""
Content Agent — Creates and publishes content: articles, newsletters, videos, podcasts.

Publishes to: Medium, Dev.to, Hashnode, email (Resend/Mailgun), social media.
"""

from __future__ import annotations

import logging
from typing import Any

from apps.core.agents.base_agent import BaseAgent

logger = logging.getLogger("aria.business.content")


class ContentAgent(BaseAgent):
    IDENTITY = (
        "You are ARIA AI's Content Agent. You create high-quality content that drives traffic, "
        "generates leads, and positions the brand. You write SEO articles, viral newsletters, "
        "and video scripts. You publish directly to the configured platforms."
    )

    def __init__(self) -> None:
        super().__init__(
            name="content",
            description="Creates and publishes articles, newsletters, and social posts across all platforms",
            capabilities=[
                "article_writing",
                "newsletter",
                "social_posts",
                "seo_content",
                "publishing",
                "email_marketing",
            ],
        )

    async def _execute(self, context: dict[str, Any]) -> dict[str, Any]:
        mission = context.get("mission", "Create article")
        topic = context.get("topic", mission)
        content_type = context.get("type", "article")  # article|newsletter|social|all
        auto_publish = context.get("auto_publish", False)
        platforms = context.get("platforms", ["devto"])

        results: dict[str, Any] = {"success": True, "agent": "content", "topic": topic}

        if content_type in ("article", "all"):
            article = await self._write_article(topic)
            results["article"] = article
            if auto_publish and article.get("success"):
                pub = await self._publish_article(
                    article["title"], article["content"], article.get("tags", []), platforms
                )
                results["article_published"] = pub

        if content_type in ("newsletter", "all"):
            newsletter = await self._write_newsletter(topic)
            results["newsletter"] = newsletter
            if auto_publish and newsletter.get("success"):
                email_result = await self._send_newsletter(
                    newsletter["subject"], newsletter["body"]
                )
                results["newsletter_sent"] = email_result

        if content_type in ("social", "all"):
            from apps.core.tools.social_engine import SocialContentEngine

            social = await SocialContentEngine().create_content_pack(topic=topic)
            results["social"] = social

        results["summary"] = f"Content created for '{topic}' — type: {content_type}"
        return results

    async def _write_article(self, topic: str) -> dict:
        """Writes a complete SEO article of ~1500 words."""
        # Research first
        from apps.core.tools.web_tools import WebTools

        search = await WebTools().search_web(f"{topic} guide 2025", num_results=5)
        context_data = ""
        if search.get("success"):
            context_data = "\n".join(
                f"- {r.get('title', '')}: {r.get('snippet', '')[:150]}"
                for r in search.get("results", [])[:4]
            )

        article_content = await self.think(
            system=self.IDENTITY,
            user=(
                f"Write a complete SEO article about: {topic}\n"
                f"Research context: {context_data}\n\n"
                f"Structure: H1 title (SEO), intro (150 words), "
                f"5-7 H2 sections with substantial content, conclusion with CTA. "
                f"Total: ~1500 words. Include real examples and data."
            ),
        )

        title = (
            article_content.split("\n")[0].lstrip("#").strip()[:100] if article_content else topic
        )
        tags = [topic.split()[0], "AI", "productivity", "technology"]

        return {
            "success": bool(article_content),
            "title": title,
            "content": article_content,
            "tags": tags,
            "word_count": len(article_content.split()) if article_content else 0,
        }

    async def _write_newsletter(self, topic: str) -> dict:
        """Writes a high-open-rate newsletter."""
        content = await self.think(
            system=self.IDENTITY,
            user=(
                f"Write a newsletter about: {topic}\n\n"
                f"Format:\n"
                f"Subject Line: (max 50 chars, high open rate)\n"
                f"Preview Text: (90 chars)\n"
                f"---\n"
                f"Body: Personal greeting, 3 actionable insights, 1 free resource, clear CTA.\n"
                f"Length: 300-400 words. Tone: friendly but professional."
            ),
        )

        lines = content.split("\n") if content else []
        subject = ""
        for line in lines[:5]:
            if "Subject" in line:
                subject = line.split(":", 1)[-1].strip()
                break

        return {
            "success": bool(content),
            "subject": subject or f"Newsletter: {topic}",
            "body": content,
        }

    async def _publish_article(self, title: str, content: str, tags: list, platforms: list) -> dict:
        from apps.core.tools.publishing_tools import PublishingTools

        pt = PublishingTools()
        article = {
            "title": title,
            "body": content,
            "body_html": content,
            "tags": tags,
            "meta_description": "",
        }
        results = {}
        for platform in platforms:
            try:
                if platform == "devto":
                    results[platform] = await pt.publish_devto(article)
                elif platform == "medium":
                    results[platform] = await pt.publish_medium(article)
                elif platform == "hashnode":
                    results[platform] = await pt.publish_hashnode(article)
            except Exception as exc:
                results[platform] = {"success": False, "error": str(exc)}
        return results

    async def _send_newsletter(self, subject: str, body: str) -> dict:
        try:
            from apps.core.tools.publishing_tools import PublishingTools

            return await PublishingTools().send_newsletter(subject, body)
        except Exception as exc:
            return {"success": False, "error": str(exc)}
