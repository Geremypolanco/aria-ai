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

import logging
from typing import Any

from apps.core.agents.base_agent import BaseAgent

logger = logging.getLogger("aria.content_agent")


class ContentAgent(BaseAgent):
    """
    Agente de generación y monetización de contenido.
    Opera de forma completamente autónoma.
    """

    def __init__(self) -> None:
        super().__init__(
            name="content",
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
        if task == "trending_only":
            return await self._get_trends_report()
        if task == "create_product":
            topic = context.get("topic", "inteligencia artificial para negocios")
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
        """Ejecuta tareas de creación multimedia real."""
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
        """Pipeline completo: tendencias → artículos → publicación → distribución."""
        from apps.core.tools.content_pipeline import ContentPipeline

        logger.info(
            "[ContentAgent] Iniciando pipeline completo — %d artículos en %s",
            num_articles,
            language,
        )

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
        result["summary"] = f"Pipeline completado: {articles_count} artículos publicados. " + (
            "Producto digital creado en Gumroad."
            if result.get("digital_product", {}).get("success")
            else ""
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

    # ── CAPACIDADES HF (siempre disponibles con HF_TOKEN) ────────────────────

    async def _translate_with_hf(self, text: str, source: str = "en", target: str = "es") -> str:
        """Traduce texto usando HuggingFace Helsinki-NLP."""
        try:
            from apps.core.tools.hf_discovery import get_hf

            result = await get_hf().translate(text, source_lang=source, target_lang=target)
            if result.get("success") and result.get("translation"):
                return result["translation"]
        except Exception as exc:
            logger.warning("[ContentAgent] HF translate failed: %s", exc)
        return text  # fallback: texto original

    async def _analyze_content_sentiment(self, text: str) -> dict:
        """Analiza el sentimiento de un texto con HuggingFace."""
        try:
            from apps.core.tools.hf_discovery import get_hf

            return await get_hf().analyze_sentiment(text[:500])
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    async def _classify_topic(self, text: str, topics: list) -> dict:
        """Clasifica el tema de un texto sin entrenamiento previo."""
        try:
            from apps.core.tools.hf_discovery import get_hf

            return await get_hf().classify_text(text[:400], topics)
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    async def _generate_cover_image(self, title: str) -> dict:
        """Genera imagen de portada para un artículo usando FLUX/SDXL."""
        try:
            from apps.core.tools.hf_discovery import get_hf

            prompt = f"Professional blog cover image for article: {title}. Modern, clean design, tech aesthetic."
            return await get_hf().generate_image(prompt)
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    async def _summarize_for_social(self, article_text: str, max_length: int = 150) -> str:
        """Resume artículo largo para posts de redes sociales."""
        try:
            from apps.core.tools.hf_discovery import get_hf

            result = await get_hf().summarize(article_text[:2000], max_length=max_length)
            if result.get("success") and result.get("summary"):
                return result["summary"]
        except Exception as exc:
            logger.warning("[ContentAgent] HF summarize failed: %s", exc)
        return article_text[:max_length]

    async def _extract_article_entities(self, text: str) -> dict:
        """Extrae personas, empresas y temas de un artículo para SEO y targeting."""
        try:
            from apps.core.tools.hf_discovery import get_hf

            return await get_hf().extract_entities(text[:512])
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    async def get_hf_capabilities(self) -> dict:
        """Reporta qué capacidades HF están disponibles para este agente."""
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
