"""
google_tools.py — Integración con Google APIs: YouTube, Search Console, Trends.
"""
from __future__ import annotations
import logging
from typing import Any, Optional
import httpx
from apps.core.config import settings

logger = logging.getLogger("aria.google_tools")


class GoogleTools:
    """Integración con Google APIs: YouTube Data API y Search Console."""

    def __init__(self) -> None:
        self._http = httpx.AsyncClient(timeout=20.0)
        self._api_key = settings.GOOGLE_API_KEY

    def _configured(self) -> bool:
        return bool(self._api_key)

    async def youtube_search_trending(self, query: str, max_results: int = 10) -> dict[str, Any]:
        """Busca videos trending en YouTube sobre un tema."""
        if not self._configured():
            return {"success": False, "error": "GOOGLE_API_KEY no configurado"}
        try:
            res = await self._http.get(
                "https://www.googleapis.com/youtube/v3/search",
                params={
                    "part": "snippet",
                    "q": query,
                    "type": "video",
                    "order": "viewCount",
                    "maxResults": max_results,
                    "relevanceLanguage": "es",
                    "key": self._api_key,
                },
            )
            if res.status_code == 200:
                items = res.json().get("items", [])
                videos = [
                    {
                        "title": item["snippet"]["title"],
                        "channel": item["snippet"]["channelTitle"],
                        "video_id": item["id"].get("videoId", ""),
                        "description": item["snippet"].get("description", "")[:200],
                        "published": item["snippet"].get("publishedAt", ""),
                    }
                    for item in items
                ]
                return {"success": True, "query": query, "videos": videos, "count": len(videos)}
            return {"success": False, "error": f"YouTube API HTTP {res.status_code}: {res.text[:200]}"}
        except Exception as exc:
            logger.error("[GoogleTools] youtube_search error: %s", exc)
            return {"success": False, "error": str(exc)}

    async def youtube_get_video_stats(self, video_id: str) -> dict[str, Any]:
        """Obtiene estadísticas de un video de YouTube."""
        if not self._configured():
            return {"success": False, "error": "GOOGLE_API_KEY no configurado"}
        try:
            res = await self._http.get(
                "https://www.googleapis.com/youtube/v3/videos",
                params={"part": "statistics,snippet", "id": video_id, "key": self._api_key},
            )
            if res.status_code == 200:
                items = res.json().get("items", [])
                if not items:
                    return {"success": False, "error": "Video no encontrado"}
                item = items[0]
                stats = item.get("statistics", {})
                return {
                    "success": True,
                    "title": item["snippet"]["title"],
                    "views": int(stats.get("viewCount", 0)),
                    "likes": int(stats.get("likeCount", 0)),
                    "comments": int(stats.get("commentCount", 0)),
                    "channel": item["snippet"]["channelTitle"],
                }
            return {"success": False, "error": f"HTTP {res.status_code}"}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    async def get_trending_searches(self, geo: str = "US", language: str = "en") -> dict[str, Any]:
        """
        Obtiene temas trending via Google Trends RSS.
        No requiere API key — usa el feed público.
        """
        try:
            res = await self._http.get(
                "https://trends.google.com/trends/trendingsearches/daily/rss",
                params={"geo": geo},
                timeout=15.0,
            )
            if res.status_code == 200:
                import re
                titles = re.findall(r"<title><!\[CDATA\[(.*?)\]\]></title>", res.text)
                traffic = re.findall(r"<ht:approx_traffic>(.*?)</ht:approx_traffic>", res.text)
                trends = [
                    {"topic": t, "traffic": tr}
                    for t, tr in zip(titles[1:], traffic)  # Skip first (feed title)
                ]
                return {"success": True, "geo": geo, "trends": trends[:20], "count": len(trends)}
            return {"success": False, "error": f"HTTP {res.status_code}"}
        except Exception as exc:
            logger.error("[GoogleTools] trending error: %s", exc)
            return {"success": False, "error": str(exc)}

    async def analyze_keyword_opportunity(self, keyword: str) -> dict[str, Any]:
        """
        Analiza oportunidad de un keyword usando YouTube como proxy de demanda.
        Más videos de baja calidad = mayor oportunidad.
        """
        search_res = await self.youtube_search_trending(keyword, max_results=20)
        if not search_res.get("success"):
            return search_res

        videos = search_res.get("videos", [])
        channels = list(set(v["channel"] for v in videos))
        opportunity_score = min(10, max(1, 10 - len(channels) // 2))

        return {
            "success": True,
            "keyword": keyword,
            "video_count": len(videos),
            "unique_channels": len(channels),
            "opportunity_score": opportunity_score,
            "top_channels": channels[:5],
            "recommendation": "Alto potencial" if opportunity_score >= 7 else "Competencia moderada" if opportunity_score >= 4 else "Mercado saturado",
        }
