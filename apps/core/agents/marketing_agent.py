"""
MarketingAgent — Crea y distribuye contenido automatizado.
Usa: Buffer (redes sociales), Mailchimp (email), Google Trends (tendencias),
     Pexels (imágenes), ElevenLabs (voz), Canva (diseño), Cloudinary (CDN).
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
            name="marketing_agent",
            description="Marketing y redes sociales — contenido automatizado",
            capabilities=[
                "content_creation", "social_posting", "email_campaigns",
                "trend_analysis", "image_generation", "seo_content",
            ],
        )

    async def _execute(self, context: dict[str, Any]) -> dict[str, Any]:
        task = context.get("task", "")
        niche = context.get("niche", "digital products")
        language = context.get("language", "es")
        product = context.get("product", {})

        results: dict[str, Any] = {"success": True, "agent": "marketing_agent"}

        # Obtener trending topics
        trends = await self._get_trending_topics(niche)
        results["trends"] = trends

        # Crear pack de contenido con IA
        content_pack = await self._create_content_pack(niche, language, trends, product, task)
        results["content_pack"] = content_pack

        # Publicar en redes sociales via Buffer
        if content_pack.get("social_posts"):
            social_result = await self._publish_social_posts(content_pack["social_posts"])
            results["social_posting"] = social_result

        # Crear campaña de email si hay producto
        if product and product.get("name"):
            email_result = await self._send_email_campaign(product, content_pack, language)
            results["email_campaign"] = email_result

        # Guardar en Supabase
        await self._save_campaign(niche, content_pack, results)

        await self._log("marketing_executed", f"Nicho: {niche} | Posts: {len(content_pack.get('social_posts', []))}")
        return results

    async def _get_trending_topics(self, niche: str) -> list[str]:
        """Obtiene trending topics de Google Trends y NewsAPI."""
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
        """Genera un pack completo de contenido con IA."""
        product_name = product.get("name", "")
        product_url = product.get("url", "")

        prompt = (
            f"Eres un experto en marketing digital de productos digitales.\n"
            f"Nicho: {niche}\n"
            f"Idioma objetivo: {language}\n"
            f"Trending topics: {', '.join(trends[:5])}\n"
            f"Producto a promocionar: {product_name or 'sin producto específico'}\n"
            f"URL del producto: {product_url}\n"
            f"Tarea adicional: {task}\n\n"
            "Genera un pack de contenido completo en JSON con:\n"
            "{\n"
            '  "social_posts": [\n'
            '    {"platform": "twitter", "text": "tweet de 280 chars con hashtags"},\n'
            '    {"platform": "linkedin", "text": "post profesional de 500 chars"},\n'
            '    {"platform": "instagram", "text": "caption con emojis y hashtags"}\n'
            '  ],\n'
            '  "email_subject": "Asunto del email",\n'
            '  "email_body": "Cuerpo del email en HTML básico",\n'
            '  "blog_title": "Título de artículo de blog SEO",\n'
            '  "blog_intro": "Párrafo introductorio del artículo (300 palabras)",\n'
            '  "seo_keywords": ["keyword1", "keyword2", "keyword3"],\n'
            '  "cta": "Call to action principal"\n'
            "}"
        )

        content_json = await self.think(
            system="Eres un copywriter experto en marketing digital. Responde SOLO con JSON válido.",
            user=prompt,
            model=AIModel.CREATIVE,
        )

        try:
            import json, re
            match = re.search(r"\{.*\}", content_json or "", re.DOTALL)
            if match:
                return json.loads(match.group())
        except Exception:
            pass

        # Fallback básico
        return {
            "social_posts": [
                {"platform": "twitter", "text": f"🚀 Descubre lo mejor en {niche}. #digitalproducts #{niche.replace(' ', '')}"},
                {"platform": "linkedin", "text": f"Nuevo contenido sobre {niche} disponible. Aprende cómo monetizar este nicho."},
            ],
            "email_subject": f"Oportunidad en {niche} — Actúa ahora",
            "email_body": f"<h2>Oportunidad en {niche}</h2><p>Hemos identificado una gran oportunidad en este mercado.</p>",
            "blog_title": f"Cómo monetizar {niche} en 2025",
            "blog_intro": f"El mercado de {niche} está en pleno auge...",
            "seo_keywords": [niche, "productos digitales", "monetización"],
            "cta": "Descúbrelo ahora",
        }

    async def _publish_social_posts(self, posts: list[dict]) -> dict[str, Any]:
        """Publica posts en redes sociales via Buffer."""
        try:
            from apps.core.tools.buffer_tools import BufferTools
            buffer = BufferTools()
            results = []
            for post in posts:
                text = post.get("text", "")
                if not text:
                    continue
                res = await buffer.post_update(text=text, now=False)
                results.append({"platform": post.get("platform", "?"), "success": res.get("success", False)})
                logger.info("[MarketingAgent] Buffer post: %s", res)
            return {"success": True, "posts_queued": len([r for r in results if r["success"]]), "results": results}
        except Exception as exc:
            logger.error("[MarketingAgent] Buffer error: %s", exc)
            return {"success": False, "error": str(exc), "note": "BUFFER_TOKEN no configurado o error de API"}

    async def _send_email_campaign(self, product: dict, content_pack: dict, language: str) -> dict[str, Any]:
        """Envía campaña de email via Mailchimp."""
        try:
            from apps.core.tools.mailchimp_tools import MailchimpTools
            mailchimp = MailchimpTools()

            # Obtener primera lista disponible
            lists_res = await mailchimp.get_lists()
            if not lists_res.get("success") or not lists_res.get("lists"):
                return {"success": False, "error": "Sin listas de Mailchimp disponibles"}

            list_id = lists_res["lists"][0]["id"]

            result = await mailchimp.create_campaign(
                list_id=list_id,
                subject=content_pack.get("email_subject", f"Oferta especial — {product.get('name', 'Producto')}"),
                from_name="ARIA AI",
                reply_to="noreply@aria-ai.com",
                body_html=content_pack.get("email_body", "<p>Nuevo producto disponible.</p>"),
                preview_text=content_pack.get("cta", "Actúa ahora"),
            )
            return result
        except Exception as exc:
            logger.error("[MarketingAgent] Mailchimp error: %s", exc)
            return {"success": False, "error": str(exc), "note": "Mailchimp no configurado"}

    async def _save_campaign(self, niche: str, content_pack: dict, results: dict) -> None:
        """Guarda la campaña en Supabase."""
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
            logger.warning("[MarketingAgent] Error guardando campaña: %s", exc)
