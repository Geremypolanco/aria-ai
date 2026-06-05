"""
ARIA Content Agent — Agente especializado en generación y monetización de contenido.

Ejecuta el pipeline completo:
1. Detecta tendencias (HN + Reddit + Product Hunt)
2. Genera artículos SEO (Groq/HuggingFace)
3. Inyecta links de afiliado (Amazon + ClickBank)
4. Publica en Medium + Dev.to + Hashnode
5. Distribuye en redes sociales
6. Crea productos digitales en Gumroad
7. Registra todo en Supabase

Se ejecuta en cada ciclo autónomo del orchestrator.
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Any

from apps.core.agents.base_agent import BaseAgent
from apps.core.config import settings

logger = logging.getLogger("aria.content_agent")


class ContentAgent(BaseAgent):
    """
    Agente de generación y monetización de contenido.
    Opera de forma completamente autónoma.
    """

    def __init__(self) -> None:
        super().__init__(
            name="content_agent",
            description="Genera y monetiza contenido automaticamente",
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
        """Punto de entrada del agente."""
        task = context.get("task", "full_pipeline")
        language = context.get("language", "es")
        num_articles = context.get("num_articles", 3)

        if task == "full_pipeline":
            return await self._run_full_pipeline(language, num_articles)
        elif task == "trending_only":
            return await self._get_trends_report()
        elif task == "create_product":
            topic = context.get("topic", "inteligencia artificial para negocios")
            category = context.get("category", "business")
            return await self._create_product(topic, category)
        elif task == "newsletter":
            return await self._send_newsletter_digest()
        else:
            return await self._run_full_pipeline(language, num_articles)

    async def _run_full_pipeline(self, language: str = "es", num_articles: int = 3) -> dict:
        """Pipeline completo: tendencias → artículos → publicación → distribución."""
        from apps.core.tools.content_pipeline import ContentPipeline

        logger.info("[ContentAgent] Iniciando pipeline completo — %d artículos en %s", num_articles, language)

        pipeline = ContentPipeline()
        result = await pipeline.run_pipeline(num_articles=num_articles, language=language)

        # Si el pipeline tuvo éxito, crear un producto digital sobre el tema más popular
        if result.get("success") and result.get("articles"):
            top_article = result["articles"][0]
            topic = top_article.get("title", "inteligencia artificial")
            category = "tech"  # default

            try:
                product_result = await self._create_product(topic, category)
                result["digital_product"] = product_result
            except Exception as exc:
                logger.warning("[ContentAgent] Error creando producto digital: %s", exc)

        # Construir resumen
        articles_count = result.get("articles_published", 0)
        result["summary"] = (
            f"Pipeline completado: {articles_count} artículos publicados. "
            + (f"Producto digital creado en Gumroad." if result.get("digital_product", {}).get("success") else "")
        )

        logger.info("[ContentAgent] Pipeline completado — %d artículos", articles_count)
        return result

    async def _get_trends_report(self) -> dict:
        """Obtiene y reporta las tendencias actuales."""
        from apps.core.tools.content_pipeline import ContentPipeline
        pipeline = ContentPipeline()
        topics = await pipeline.get_trending_topics(limit=15)
        return {
            "success": True,
            "topics": topics,
            "count": len(topics),
            "summary": f"Encontré {len(topics)} trending topics",
        }

    async def _create_product(self, topic: str, category: str) -> dict:
        """Crea un producto digital en Gumroad."""
        from apps.core.tools.affiliate_tools import AffiliateTools
        tools = AffiliateTools()
        result = await tools.auto_create_digital_product(topic, category)
        return result

    async def _send_newsletter_digest(self) -> dict:
        """Envía digest de los últimos artículos publicados."""
        try:
            from apps.core.memory.supabase_client import get_db
            from apps.core.tools.publishing_tools import PublishingTools

            db = get_db()
            publisher = PublishingTools()

            # Obtener últimos artículos
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
                return {"success": False, "error": "No hay artículos recientes"}

            # Construir newsletter
            html = "<h1>ARIA Digest — Últimos artículos</h1>\n<ul>"
            text = "ARIA Digest — Últimos artículos\n\n"
            for a in articles:
                html += f'<li><a href="{a.get("url", "")}">{a.get("name", "")}</a></li>'
                text += f"- {a.get('name', '')}: {a.get('url', '')}\n"
            html += "</ul>"

            send_result = await publisher.send_newsletter(
                subject="ARIA Digest — Nuevos artículos publicados",
                html_content=html,
                plain_text=text,
            )
            return send_result

        except Exception as exc:
            logger.error("[ContentAgent] Newsletter error: %s", exc)
            return {"success": False, "error": str(exc)}
