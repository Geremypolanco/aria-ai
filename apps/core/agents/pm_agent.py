"""
PMAgent — Product Manager Agent
Analiza mercados, identifica nichos rentables y score de oportunidades.
"""
from __future__ import annotations

import logging
from typing import Any

import httpx

from apps.core.agents.base_agent import BaseAgent
from apps.core.config import settings
from apps.core.tools.ai_client import AIModel

logger = logging.getLogger("aria.pm_agent")


class PMAgent(BaseAgent):
    def __init__(self) -> None:
        super().__init__(
            name="pm_agent",
            description="Analista de mercado y gestor de producto",
            capabilities=[
                "niche_analysis", "opportunity_scoring",
                "affiliate_research", "keyword_research",
            ],
        )

    async def _execute(self, context: dict[str, Any]) -> dict[str, Any]:
        task = context.get("task", "")
        market_focus = context.get("market_focus", "digital products")
        language = context.get("primary_language", "en")

        keywords = await self.get_trending_keywords(market_focus, language)
        niche_data = await self.analyze_niche(market_focus, language, keywords)
        affiliates = await self.find_affiliate_programs(market_focus)
        score = await self.score_opportunity(niche_data)

        result = {
            "success": True,
            "agent": "pm_agent",
            "niche": market_focus,
            "score": score,
            "keywords": keywords[:10],
            "affiliates": affiliates[:5],
            "niche_data": niche_data,
        }

        # Guardar en Supabase
        if score.get("opportunity_score", 0) >= 6:
            await self._save_intelligence(market_focus, language, niche_data, score)

        await self._log("niche_analysis", f"Nicho: {market_focus} | Score: {score}")
        return result

    async def analyze_niche(
        self, niche: str, language: str, keywords: list[str]
    ) -> dict[str, Any]:
        """Analiza un nicho de mercado usando IA + APIs."""
        news_context = await self._fetch_niche_news(niche)
        serp_context = await self._fetch_serp_data(niche)

        analysis = await self.think(
            system=(
                "Eres un analista de mercado experto en negocios digitales globales. "
                "Analiza nichos con enfoque en monetización inmediata y escalabilidad."
            ),
            user=(
                f"Nicho: {niche}\nIdioma objetivo: {language}\n"
                f"Keywords trending: {', '.join(keywords[:5])}\n"
                f"Noticias: {news_context[:500]}\n"
                f"SERP data: {serp_context[:500]}\n\n"
                "Devuelve JSON con:\n"
                '{"demand_score": 1-10, "competition_score": 1-10, '
                '"monetization_potential": "alto|medio|bajo", '
                '"recommended_products": ["producto1", "producto2"], '
                '"target_audience": "descripción", '
                '"entry_barriers": "descripción", '
                '"quick_win_strategy": "descripción"}'
            ),
            model=AIModel.STRATEGY,
            json_mode=True,
        )
        return analysis or {}

    async def find_affiliate_programs(self, niche: str) -> list[dict[str, Any]]:
        """Identifica programas de afiliados relevantes para el nicho."""
        result = await self.think(
            system="Eres experto en marketing de afiliados con conocimiento profundo de programas de comisiones altas.",
            user=(
                f"Nicho: {niche}\n\n"
                "Lista los 5 mejores programas de afiliados para este nicho. JSON:\n"
                '[{"name": "...", "commission_pct": 0, "cookie_days": 0, '
                '"url": "...", "payment_method": "...", "notes": "..."}]'
            ),
            model=AIModel.FAST,
            json_mode=True,
        )
        return result if isinstance(result, list) else []

    async def score_opportunity(self, niche_data: dict[str, Any]) -> dict[str, Any]:
        """Calcula el score de oportunidad compuesto."""
        demand = niche_data.get("demand_score", 5)
        competition = niche_data.get("competition_score", 5)
        # Fórmula: demanda alta + competencia baja = score alto
        opportunity_score = round((demand * 0.6) + ((10 - competition) * 0.4), 1)
        return {
            "opportunity_score": min(10, opportunity_score),
            "demand_score": demand,
            "competition_score": competition,
            "recommendation": "GO" if opportunity_score >= 6 else "SKIP",
        }

    async def get_trending_keywords(self, niche: str, language: str) -> list[str]:
        """Obtiene keywords trending para el nicho."""
        if settings.SERP_API_KEY:
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    res = await client.get(
                        "https://serpapi.com/search",
                        params={
                            "api_key": settings.SERP_API_KEY,
                            "engine": "google_autocomplete",
                            "q": niche,
                            "gl": "us",
                            "hl": language,
                        },
                    )
                    if res.status_code == 200:
                        suggestions = res.json().get("suggestions", [])
                        return [s.get("value", "") for s in suggestions[:10]]
            except Exception as exc:
                logger.warning("[PMAgent] SERP keywords error: %s", exc)

        # Fallback: IA
        result = await self.think(
            system="Eres experto en SEO y keyword research.",
            user=f"Lista 10 keywords long-tail trending para el nicho '{niche}' en idioma '{language}'. Devuelve JSON: [\"keyword1\", \"keyword2\"]",
            model=AIModel.FAST,
            json_mode=True,
        )
        return result if isinstance(result, list) else [niche]

    async def _fetch_niche_news(self, niche: str) -> str:
        if not settings.NEWS_API_KEY:
            return ""
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                res = await client.get(
                    "https://newsapi.org/v2/everything",
                    params={
                        "apiKey": settings.NEWS_API_KEY,
                        "q": niche,
                        "language": "en",
                        "sortBy": "publishedAt",
                        "pageSize": 5,
                    },
                )
                if res.status_code == 200:
                    articles = res.json().get("articles", [])
                    return " | ".join([a.get("title", "") for a in articles])
        except Exception:
            pass
        return ""

    async def _fetch_serp_data(self, niche: str) -> str:
        if not settings.SERP_API_KEY:
            return ""
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                res = await client.get(
                    "https://serpapi.com/search",
                    params={
                        "api_key": settings.SERP_API_KEY,
                        "engine": "google",
                        "q": f"{niche} buy online",
                        "num": 5,
                    },
                )
                if res.status_code == 200:
                    results = res.json().get("organic_results", [])
                    return " | ".join([r.get("title", "") for r in results[:5]])
        except Exception:
            pass
        return ""

    async def _save_intelligence(
        self, niche: str, language: str, data: dict, score: dict
    ) -> None:
        try:
            from apps.core.memory.supabase_client import get_db
            db = get_db()
            await db.save_market_intelligence(
                niche=niche,
                market="global",
                language=language,
                trend_score=int(data.get("demand_score", 5)),
                competition_score=int(data.get("competition_score", 5)),
                opportunity_score=int(score.get("opportunity_score", 5)),
                data=data,
            )
        except Exception as exc:
            logger.warning("[PMAgent] No se pudo guardar inteligencia: %s", exc)
