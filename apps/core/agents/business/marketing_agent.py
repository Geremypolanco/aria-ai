"""
Marketing Agent — SEO, contenido viral, campañas y crecimiento de marca.

Maneja: SEO research, blog posts, social media calendar, email campaigns,
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
        "Eres el Marketing Agent de ARIA AI. Eres un CMO digital experto en growth hacking, "
        "SEO, content marketing y viral loops. Tu objetivo: máximo alcance y conversión. "
        "Generas y ejecutas campañas reales, no solo planes."
    )

    def __init__(self) -> None:
        super().__init__(
            name="marketing",
            description="SEO, contenido viral, campañas de email, redes sociales y crecimiento de marca",
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
        mission = context.get("mission", "Crear estrategia de marketing completa")
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

        # Publicar contenido si está configurado
        if context.get("auto_publish") and results.get("social_content"):
            pub_result = await self._publish_social(results["social_content"])
            results["published"] = pub_result

        results["summary"] = f"Estrategia de marketing generada para '{niche}'. Canales: {channels}"
        return results

    async def _create_seo_strategy(self, niche: str, mission: str) -> dict:
        strategy = await self.think(
            system=self.IDENTITY,
            user=(
                f"Nicho: {niche}\nMisión: {mission}\n\n"
                f"Genera: 10 keywords de alta intención, 5 títulos de artículos SEO, "
                f"meta descriptions, estructura de sitio, y estrategia de backlinks. "
                f"Formato estructurado."
            ),
        )
        return {"strategy": strategy, "type": "seo"}

    async def _create_social_content(self, niche: str, mission: str) -> dict:
        """Genera contenido para todas las plataformas principales."""
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
                f"Crea una campaña de email de 5 emails (secuencia de nurturing) para el nicho '{niche}'. "
                f"Objetivo: {mission}. Incluye: asunto, preview text, cuerpo (200 palabras), CTA. "
                f"Formato JSON array."
            ),
        )
        return {"campaign_sequence": campaign, "emails": 5}

    async def _create_blog_strategy(self, niche: str) -> dict:
        strategy = await self.think(
            system=self.IDENTITY,
            user=(
                f"Nicho: {niche}\n"
                f"Genera 10 ideas de artículos de blog con: título (SEO-optimizado), "
                f"intro de 50 palabras, outline de 5 secciones, keywords target. "
                f"Ordenados por potencial de tráfico."
            ),
        )
        return {"blog_ideas": strategy}

    async def _publish_social(self, social_content: dict) -> dict:
        """Publica contenido generado en redes sociales activas."""
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
