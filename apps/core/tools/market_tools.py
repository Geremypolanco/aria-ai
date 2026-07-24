"""
market_tools.py — Market intelligence tools.
NewsAPI, SerpAPI, opportunity scoring, affiliates.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from apps.core.config import settings

logger = logging.getLogger("aria.market_tools")


class MarketTools:
    """Market research tools."""

    def __init__(self) -> None:
        self._http = httpx.AsyncClient(timeout=15.0)

    # ── NEWS (NewsAPI) ────────────────────────────────

    async def get_trending_news(
        self,
        query: str = "digital products make money online",
        language: str = "en",
        page_size: int = 10,
    ) -> list[dict[str, Any]]:
        """Gets trending news via NewsAPI."""
        if not settings.NEWS_API_KEY:
            logger.warning("[MarketTools] NEWS_API_KEY not configured")
            return []
        try:
            res = await self._http.get(
                "https://newsapi.org/v2/everything",
                params={
                    "q": query,
                    "language": language,
                    "sortBy": "publishedAt",
                    "pageSize": page_size,
                    "apiKey": settings.NEWS_API_KEY,
                },
            )
            if res.status_code == 200:
                articles = res.json().get("articles", [])
                return [
                    {
                        "title": a.get("title", ""),
                        "description": a.get("description", ""),
                        "url": a.get("url", ""),
                        "source": a.get("source", {}).get("name", ""),
                        "published_at": a.get("publishedAt", ""),
                    }
                    for a in articles
                    if a.get("title")
                ]
            logger.warning("[MarketTools] NewsAPI HTTP %d", res.status_code)
        except Exception as exc:
            logger.error("[MarketTools] NewsAPI error: %s", exc)
        return []

    async def get_top_headlines(
        self, category: str = "technology", country: str = "us"
    ) -> list[dict[str, Any]]:
        """Top headlines by category."""
        if not settings.NEWS_API_KEY:
            return []
        try:
            res = await self._http.get(
                "https://newsapi.org/v2/top-headlines",
                params={
                    "category": category,
                    "country": country,
                    "pageSize": 10,
                    "apiKey": settings.NEWS_API_KEY,
                },
            )
            if res.status_code == 200:
                return res.json().get("articles", [])
        except Exception as exc:
            logger.error("[MarketTools] Top headlines error: %s", exc)
        return []

    # ── SEARCH (SerpAPI) ────────────────────────────────

    async def search_trends(self, query: str, num_results: int = 10) -> list[dict[str, Any]]:
        """Searches for trends and results via SerpAPI."""
        if not settings.SERP_API_KEY:
            logger.warning("[MarketTools] SERP_API_KEY not configured")
            return []
        try:
            res = await self._http.get(
                "https://serpapi.com/search",
                params={
                    "q": query,
                    "api_key": settings.SERP_API_KEY,
                    "num": num_results,
                    "engine": "google",
                },
            )
            if res.status_code == 200:
                data = res.json()
                organic = data.get("organic_results", [])
                return [
                    {
                        "title": r.get("title", ""),
                        "link": r.get("link", ""),
                        "snippet": r.get("snippet", ""),
                        "position": r.get("position", 0),
                    }
                    for r in organic
                ]
            logger.warning("[MarketTools] SerpAPI HTTP %d", res.status_code)
        except Exception as exc:
            logger.error("[MarketTools] SerpAPI error: %s", exc)
        return []

    async def get_related_searches(self, query: str) -> list[str]:
        """Gets related searches from Google."""
        if not settings.SERP_API_KEY:
            return []
        try:
            res = await self._http.get(
                "https://serpapi.com/search",
                params={
                    "q": query,
                    "api_key": settings.SERP_API_KEY,
                    "engine": "google",
                },
            )
            if res.status_code == 200:
                data = res.json()
                related = data.get("related_searches", [])
                return [r.get("query", "") for r in related if r.get("query")]
        except Exception as exc:
            logger.error("[MarketTools] Related searches error: %s", exc)
        return []

    async def search_affiliate_programs(self, niche: str) -> list[dict[str, Any]]:
        """Searches for affiliate programs relevant to the niche."""
        if not settings.SERP_API_KEY:
            return []
        try:
            query = f"{niche} affiliate program high commission"
            results = await self.search_trends(query, num_results=5)
            programs = []
            for r in results:
                programs.append(
                    {
                        "name": r.get("title", ""),
                        "url": r.get("link", ""),
                        "description": r.get("snippet", ""),
                        "estimated_commission": self._estimate_commission(r.get("snippet", "")),
                    }
                )
            return programs
        except Exception as exc:
            logger.error("[MarketTools] Affiliate search error: %s", exc)
        return []

    # ── OPPORTUNITY SCORING ──────────────────────────

    def score_opportunity(
        self,
        niche: str,
        news_count: int,
        search_results: list[dict],
        competition_level: str = "medium",
    ) -> dict[str, Any]:
        """Calculates a 0-100 opportunity score for a niche."""
        # Base score from recent news (demand signal)
        news_score = min(news_count * 5, 30)

        # Score from competition
        competition_scores = {"low": 40, "medium": 25, "high": 10}
        comp_score = competition_scores.get(competition_level, 20)

        # Score from result position (less domination = more opportunity)
        avg_position = sum(r.get("position", 5) for r in search_results[:5]) / max(
            len(search_results[:5]), 1
        )
        position_score = max(0, 30 - avg_position * 3)

        total = min(int(news_score + comp_score + position_score), 100)

        return {
            "niche": niche,
            "opportunity_score": total,
            "news_score": news_score,
            "competition_score": comp_score,
            "position_score": int(position_score),
            "competition_level": competition_level,
            "recommendation": self._score_recommendation(total),
        }

    def _score_recommendation(self, score: int) -> str:
        if score >= 70:
            return "🔥 HIGH — Act immediately"
        if score >= 50:
            return "✅ MEDIUM — Good opportunity, explore"
        if score >= 30:
            return "⚠️ LOW — Consider carefully"
        return "❌ VERY LOW — Avoid for now"

    def _estimate_commission(self, text: str) -> str:
        """Estimates the commission of an affiliate program from text."""
        import re

        matches = re.findall(r"(\d+)\s*%", text)
        if matches:
            max_pct = max(int(m) for m in matches)
            return f"{max_pct}%"
        if "recurring" in text.lower() or "recurrente" in text.lower():
            return "recurring"
        return "variable"

    # ── GOOGLE TRENDS (via Google API) ────────────────────

    async def get_google_trends(self, keywords: list[str]) -> dict[str, Any]:
        """Gets trend data using the Google Custom Search API."""
        if not settings.GOOGLE_API_KEY:
            return {}
        results = {}
        for kw in keywords[:3]:
            try:
                res = await self._http.get(
                    "https://www.googleapis.com/customsearch/v1",
                    params={
                        "key": settings.GOOGLE_API_KEY,
                        "q": kw,
                        "num": 5,
                    },
                )
                if res.status_code == 200:
                    data = res.json()
                    results[kw] = {
                        "total_results": data.get("searchInformation", {}).get("totalResults", "0"),
                        "items": len(data.get("items", [])),
                    }
            except Exception:
                pass
        return results

    async def close(self) -> None:
        await self._http.aclose()


# ── SINGLETON ─────────────────────────────────────────────
_instance: MarketTools | None = None


def get_market_tools() -> MarketTools:
    global _instance
    if _instance is None:
        _instance = MarketTools()
    return _instance
