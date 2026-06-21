"""
Content Agent — Crea y publica contenido: artículos, newsletters, videos, podcasts.

Publica en: Medium, Dev.to, Hashnode, email (Resend/Mailgun), redes sociales.
"""
from __future__ import annotations
import asyncio
import logging
from typing import Any
from apps.core.agents.base_agent import BaseAgent
from apps.core.tools.ai_client import AIModel

logger = logging.getLogger("aria.business.content")


class ContentAgent(BaseAgent):
    IDENTITY = (
        "Eres el Content Agent de ARIA AI. Creas contenido de alta calidad que atrae tráfico, "
        "genera leads y posiciona la marca. Escribes artículos SEO, newsletters virales, "
        "y scripts de video. Publicas directamente en las plataformas configuradas."
    )

    def __init__(self) -> None:
        super().__init__(
            name="content",
            description="Crea y publica artículos, newsletters, social posts en todas las plataformas",
            capabilities=[
                "article_writing", "newsletter", "social_posts",
                "seo_content", "publishing", "email_marketing",
            ],
        )

    async def _execute(self, context: dict[str, Any]) -> dict[str, Any]:
        mission      = context.get("mission", "Crear artículo")
        topic        = context.get("topic", mission)
        content_type = context.get("type", "article")  # article|newsletter|social|all
        auto_publish = context.get("auto_publish", False)
        platforms    = context.get("platforms", ["devto"])

        results: dict[str, Any] = {"success": True, "agent": "content", "topic": topic}

        if content_type in ("article", "all"):
            article = await self._write_article(topic)
            results["article"] = article
            if auto_publish and article.get("success"):
                pub = await self._publish_article(
                    article["title"], article["content"],
                    article.get("tags", []), platforms
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

        results["summary"] = f"Contenido creado para '{topic}' — tipo: {content_type}"
        return results

    async def _write_article(self, topic: str) -> dict:
        """Escribe artículo SEO completo de ~1500 palabras."""
        # Primero investigar
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
                f"Escribe un artículo SEO completo sobre: {topic}\n"
                f"Contexto de investigación: {context_data}\n\n"
                f"Estructura: H1 título (SEO), intro (150 words), "
                f"5-7 secciones H2 con contenido sustancial, conclusión con CTA. "
                f"Total: ~1500 palabras. Incluye ejemplos reales y datos."
            ),
        )

        title = article_content.split("\n")[0].lstrip("#").strip()[:100] if article_content else topic
        tags = [topic.split()[0], "AI", "productivity", "technology"]

        return {
            "success": bool(article_content),
            "title": title,
            "content": article_content,
            "tags": tags,
            "word_count": len(article_content.split()) if article_content else 0,
        }

    async def _write_newsletter(self, topic: str) -> dict:
        """Escribe newsletter de alta apertura."""
        content = await self.think(
            system=self.IDENTITY,
            user=(
                f"Escribe un newsletter sobre: {topic}\n\n"
                f"Formato:\n"
                f"Subject Line: (máx 50 chars, alto open rate)\n"
                f"Preview Text: (90 chars)\n"
                f"---\n"
                f"Cuerpo: Saludo personal, 3 insights accionables, 1 recurso gratuito, CTA claro.\n"
                f"Longitud: 300-400 palabras. Tono: amigable pero profesional."
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

    async def _publish_article(
        self, title: str, content: str, tags: list, platforms: list
    ) -> dict:
        from apps.core.tools.publishing_tools import PublishingTools
        pt = PublishingTools()
        article = {"title": title, "body": content, "body_html": content, "tags": tags, "meta_description": ""}
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
