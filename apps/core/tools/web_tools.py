"""
web_tools.py — Acceso real a Internet para ARIA AI.

ARIA puede navegar y extraer informacion de internet usando:
  1. SerpAPI — Google Search real (SERP_API_KEY)
  2. DuckDuckGo Instant Answer API — busqueda gratuita sin key
  3. Hacker News API — trending tech sin auth
  4. Reddit API — busqueda en subreddits sin auth
  5. Product Hunt trending — via GraphQL publico
  6. httpx — fetch de cualquier URL publica
  7. NewsAPI — noticias en tiempo real (NEWS_API_KEY)
  8. Extraccion de texto limpio de paginas web

Principio: acceso a internet REAL. Sin datos inventados.
Si una fuente falla, intenta la siguiente — siempre reporta cuales funcionaron.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import uuid
from datetime import datetime
from typing import Any

import httpx

from apps.core.config import settings

logger = logging.getLogger("aria.web_tools")


class WebTools:
    """
    Acceso real a internet para ARIA AI.
    Busca, lee y extrae informacion de cualquier fuente publica.
    """

    def __init__(self) -> None:
        self._http = httpx.AsyncClient(
            timeout=20.0,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                )
            },
            follow_redirects=True,
        )

    # ══════════════════════════════════════════════════════════════
    # BUSQUEDA WEB
    # ══════════════════════════════════════════════════════════════

    async def search_web(self, query: str, num_results: int = 10) -> dict[str, Any]:
        """
        Busqueda web real con expansion inteligente de query.
        Intenta SerpAPI primero (mejor calidad), luego DuckDuckGo + NewsAPI.
        """
        optimized_query = self._optimize_query(query)
        if optimized_query != query:
            logger.info("[WebTools] Query optimizada: %s -> %s", query, optimized_query)

        # 1. SerpAPI (si esta configurado) — Google real
        if getattr(settings, "SERP_API_KEY", None):
            result = await self._search_serpapi(optimized_query, num_results)
            if result["success"] and result.get("results"):
                return result

        # 2. DuckDuckGo Instant Answer API (sin key, siempre disponible)
        result = await self._search_duckduckgo(optimized_query)
        if result["success"] and result.get("results"):
            return result

        # 3. NewsAPI como fallback (si hay NEWS_API_KEY)
        if getattr(settings, "NEWS_API_KEY", None):
            result = await self._search_newsapi(query, num_results)
            if result["success"] and result.get("results"):
                return result

        return {
            "success": False,
            "error": "Todas las fuentes de busqueda fallaron",
            "results": [],
            "query": query,
        }

    def _optimize_query(self, query: str) -> str:
        """Optimiza la query para mejores resultados según el tipo de búsqueda."""
        q = query.strip()
        words = q.split()
        # No modificar queries ya específicas (> 6 palabras)
        if len(words) > 6:
            return q
        q_lower = q.lower()
        # Negocios y monetización
        if any(w in q_lower for w in ["vender", "negocio", "shopify", "ecommerce", "tienda"]):
            return f"{q} estrategia 2025 guía completa"
        # Preguntas de "cómo"
        if q_lower.startswith(("cómo", "como", "how to", "how do")):
            return f"{q} paso a paso tutorial 2025"
        # Tendencias y novedades
        if any(w in q_lower for w in ["tendencia", "trend", "nuevo", "latest", "mejor"]):
            return f"{q} 2025 actualizado"
        # Marketing y contenido
        if any(w in q_lower for w in ["marketing", "seo", "contenido", "social media"]):
            return f"{q} mejores prácticas ejemplos 2025"
        # AI y tecnología
        if any(w in q_lower for w in ["ai", "ia", "inteligencia artificial", "llm", "gpt"]):
            return f"{q} 2025 comparison review"
        return q

    async def _search_serpapi(self, query: str, num: int = 10) -> dict[str, Any]:
        """Busqueda via SerpAPI — resultados de Google reales."""
        try:
            res = await self._http.get(
                "https://serpapi.com/search",
                params={
                    "q": query,
                    "api_key": settings.SERP_API_KEY,
                    "engine": "google",
                    "num": num,
                    "hl": "es",
                },
            )
            if res.status_code == 200:
                data = res.json()
                organic = data.get("organic_results", [])
                return {
                    "success": True,
                    "source": "serpapi_google",
                    "query": query,
                    "results": [
                        {
                            "title": r.get("title", ""),
                            "url": r.get("link", ""),
                            "snippet": r.get("snippet", ""),
                            "position": r.get("position", i + 1),
                        }
                        for i, r in enumerate(organic[:num])
                    ],
                    "total_found": data.get("search_information", {}).get("total_results", 0),
                }
            logger.warning("[WebTools] SerpAPI HTTP %d", res.status_code)
        except Exception as exc:
            logger.error("[WebTools] serpapi error: %s", exc)
        return {"success": False, "results": [], "source": "serpapi"}

    async def _search_duckduckgo(self, query: str) -> dict[str, Any]:
        """
        Busqueda via DuckDuckGo Instant Answer API.
        Completamente gratuita, sin API key, siempre disponible.
        """
        try:
            res = await self._http.get(
                "https://api.duckduckgo.com/",
                params={
                    "q": query,
                    "format": "json",
                    "no_html": "1",
                    "skip_disambig": "1",
                },
            )
            if res.status_code == 200:
                data = res.json()
                results = []
                # Abstract (resultado principal)
                if data.get("AbstractText"):
                    results.append(
                        {
                            "title": data.get("Heading", query),
                            "url": data.get("AbstractURL", ""),
                            "snippet": data.get("AbstractText", ""),
                            "source": data.get("AbstractSource", ""),
                        }
                    )
                # Related topics
                for topic in data.get("RelatedTopics", [])[:8]:
                    if isinstance(topic, dict) and topic.get("Text"):
                        results.append(
                            {
                                "title": topic.get("Text", "")[:80],
                                "url": topic.get("FirstURL", ""),
                                "snippet": topic.get("Text", ""),
                                "source": "DuckDuckGo",
                            }
                        )
                return {
                    "success": True,
                    "source": "duckduckgo",
                    "query": query,
                    "results": results,
                }
        except Exception as exc:
            logger.error("[WebTools] duckduckgo error: %s", exc)
        return {"success": False, "results": [], "source": "duckduckgo"}

    # ══════════════════════════════════════════════════════════════
    # SCREENSHOTS Y NAVEGACION REAL
    # ══════════════════════════════════════════════════════════════

    async def take_screenshot(self, url: str, full_page: bool = False) -> dict[str, Any]:
        """
        Toma una captura de pantalla real de cualquier URL usando Playwright.
        Retorna la ruta local del archivo generado.
        """
        try:
            from playwright.async_api import async_playwright

            # Crear directorio de screenshots si no existe
            os.makedirs("screenshots", exist_ok=True)
            filename = f"screenshots/{uuid.uuid4().short if hasattr(uuid.uuid4(), 'short') else str(uuid.uuid4())[:8]}_{int(datetime.now().timestamp())}.png"

            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                context = await browser.new_context(
                    viewport={"width": 1280, "height": 800},
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                )
                page = await context.new_page()

                logger.info("[WebTools] Navegando para screenshot: %s", url)
                await page.goto(url, wait_until="networkidle", timeout=30000)

                # Esperar un poco mas por si hay animaciones
                await asyncio.sleep(2)

                await page.screenshot(path=filename, full_page=full_page)
                await browser.close()

                return {
                    "success": True,
                    "url": url,
                    "screenshot_path": filename,
                    "timestamp": datetime.now().isoformat(),
                }
        except Exception as exc:
            logger.error("[WebTools] Error tomando screenshot de %s: %s", url, exc)
            return {"success": False, "error": str(exc), "url": url}

    async def _search_newsapi(self, query: str, num: int = 10) -> dict[str, Any]:
        """Búsqueda de noticias via NewsAPI (fallback con NEWS_API_KEY)."""
        try:
            res = await self._http.get(
                "https://newsapi.org/v2/everything",
                params={
                    "q": query,
                    "apiKey": settings.NEWS_API_KEY,
                    "language": "es",
                    "sortBy": "relevancy",
                    "pageSize": num,
                },
            )
            if res.status_code == 200:
                data = res.json()
                articles = data.get("articles", [])
                return {
                    "success": bool(articles),
                    "source": "newsapi",
                    "query": query,
                    "results": [
                        {
                            "title": a.get("title", ""),
                            "url": a.get("url", ""),
                            "snippet": a.get("description", "") or a.get("content", "")[:300],
                            "published": a.get("publishedAt", ""),
                        }
                        for a in articles[:num]
                    ],
                }
        except Exception as exc:
            logger.error("[WebTools] newsapi error: %s", exc)
        return {"success": False, "results": [], "source": "newsapi"}

    # ══════════════════════════════════════════════════════════════
    # FETCH DE PAGINAS WEB
    # ══════════════════════════════════════════════════════════════

    async def fetch_page(self, url: str, max_chars: int = 5000) -> dict[str, Any]:
        """
        Descarga y extrae el texto limpio de cualquier URL publica.
        Elimina HTML, scripts, styles, nav, footer — retorna contenido legible.
        """
        try:
            res = await self._http.get(url, timeout=15.0)
            if res.status_code != 200:
                return {"success": False, "error": f"HTTP {res.status_code}", "url": url}

            html = res.text

            # Extraer titulo
            title_match = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
            title = re.sub(r"\s+", " ", title_match.group(1)).strip() if title_match else ""

            # Eliminar ruido: scripts, styles, nav, footer, header, aside, forms
            text = html
            for tag in (
                "script",
                "style",
                "nav",
                "footer",
                "header",
                "aside",
                "form",
                "noscript",
                "iframe",
            ):
                text = re.sub(
                    rf"<{tag}[^>]*>.*?</{tag}>", " ", text, flags=re.DOTALL | re.IGNORECASE
                )

            # Convertir bloques de contenido a texto legible
            text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
            text = re.sub(r"<p[^>]*>", "\n", text, flags=re.IGNORECASE)
            text = re.sub(r"<h[1-6][^>]*>", "\n## ", text, flags=re.IGNORECASE)
            text = re.sub(r"</h[1-6]>", "\n", text, flags=re.IGNORECASE)
            text = re.sub(r"<li[^>]*>", "\n- ", text, flags=re.IGNORECASE)

            # Eliminar el resto de etiquetas HTML
            text = re.sub(r"<[^>]+>", " ", text)

            # Decodificar entidades HTML comunes
            for entity, char in [
                ("&amp;", "&"),
                ("&lt;", "<"),
                ("&gt;", ">"),
                ("&quot;", '"'),
                ("&#39;", "'"),
                ("&nbsp;", " "),
            ]:
                text = text.replace(entity, char)
            text = re.sub(r"&[a-z#0-9]+;", " ", text)

            # Limpiar espacios múltiples pero preservar saltos de línea útiles
            text = re.sub(r"[ \t]+", " ", text)
            text = re.sub(r"\n{3,}", "\n\n", text)
            text = text.strip()

            return {
                "success": True,
                "url": url,
                "title": title,
                "text": text[:max_chars],
                "chars": len(text),
                "truncated": len(text) > max_chars,
            }
        except Exception as exc:
            logger.error("[WebTools] fetch_page %s: %s", url, exc)
            return {"success": False, "error": str(exc), "url": url}

    # ══════════════════════════════════════════════════════════════
    # FUENTES DE TENDENCIAS (todas gratuitas, sin key)
    # ══════════════════════════════════════════════════════════════

    async def get_hacker_news_trending(self, limit: int = 20) -> dict[str, Any]:
        """
        Top stories de Hacker News en tiempo real.
        Sin API key. Fuente de tendencias tech muy confiable.
        """
        try:
            # Obtener IDs de top stories
            ids_res = await self._http.get("https://hacker-news.firebaseio.com/v0/topstories.json")
            if ids_res.status_code != 200:
                return {"success": False, "error": f"HN API HTTP {ids_res.status_code}"}

            ids = ids_res.json()[:limit]

            # Fetch stories en paralelo
            async def get_story(story_id: int) -> dict | None:
                try:
                    r = await self._http.get(
                        f"https://hacker-news.firebaseio.com/v0/item/{story_id}.json"
                    )
                    if r.status_code == 200:
                        d = r.json()
                        return {
                            "title": d.get("title", ""),
                            "url": d.get("url", f"https://news.ycombinator.com/item?id={story_id}"),
                            "score": d.get("score", 0),
                            "comments": d.get("descendants", 0),
                            "by": d.get("by", ""),
                        }
                except Exception:
                    return None

            stories = await asyncio.gather(*[get_story(i) for i in ids])
            valid = [s for s in stories if s and s.get("title")]

            return {
                "success": True,
                "source": "hacker_news",
                "stories": sorted(valid, key=lambda x: x["score"], reverse=True),
                "count": len(valid),
            }
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    async def get_reddit_trending(
        self,
        subreddits: list[str] | None = None,
        limit: int = 15,
    ) -> dict[str, Any]:
        """
        Posts trending de Reddit (sin auth, usando JSON publico).
        Subreddits por defecto: los mas relevantes para negocios digitales.
        """
        if not subreddits:
            subreddits = [
                "entrepreneur",
                "SideProject",
                "passive_income",
                "digitalmarketing",
                "SEO",
                "affiliatemarketing",
            ]
        all_posts: list[dict] = []
        try:

            async def fetch_sub(sub: str) -> list[dict]:
                try:
                    r = await self._http.get(
                        f"https://www.reddit.com/r/{sub}/hot.json",
                        params={"limit": limit // len(subreddits) + 1},
                        headers={"User-Agent": "ARIA-AI-Bot/1.0"},
                    )
                    if r.status_code == 200:
                        posts = r.json().get("data", {}).get("children", [])
                        return [
                            {
                                "title": p["data"]["title"],
                                "url": f"https://reddit.com{p['data']['permalink']}",
                                "subreddit": sub,
                                "score": p["data"]["score"],
                                "comments": p["data"]["num_comments"],
                                "text": p["data"].get("selftext", "")[:300],
                            }
                            for p in posts
                            if not p["data"].get("stickied") and p["data"]["score"] > 10
                        ]
                except Exception:
                    return []
                return []

            results = await asyncio.gather(*[fetch_sub(s) for s in subreddits])
            for posts in results:
                all_posts.extend(posts)

            all_posts.sort(key=lambda x: x["score"], reverse=True)
            return {
                "success": True,
                "source": "reddit",
                "posts": all_posts[:limit],
                "subreddits": subreddits,
                "count": len(all_posts),
            }
        except Exception as exc:
            return {"success": False, "error": str(exc), "posts": []}

    async def get_product_hunt_trending(self, limit: int = 10) -> dict[str, Any]:
        """
        Productos trending de Product Hunt via API publica.
        Requiere PRODUCT_HUNT_TOKEN (gratuito con cuenta).
        Sin token: retorna error explicito.
        """
        token = getattr(settings, "PRODUCT_HUNT_TOKEN", None)
        if not token:
            return {
                "success": False,
                "error": "PRODUCT_HUNT_TOKEN no configurado. Crea cuenta en producthunt.com/v2/oauth/applications",
                "products": [],
            }
        try:
            query = (
                """
            {
              posts(order: VOTES, first: %d) {
                edges {
                  node {
                    id name tagline votesCount
                    website
                    topics { edges { node { name } } }
                  }
                }
              }
            }
            """
                % limit
            )
            res = await self._http.post(
                "https://api.producthunt.com/v2/api/graphql",
                json={"query": query},
                headers={"Authorization": f"Bearer {token}"},
            )
            if res.status_code == 200:
                edges = res.json().get("data", {}).get("posts", {}).get("edges", [])
                return {
                    "success": True,
                    "source": "product_hunt",
                    "products": [
                        {
                            "name": e["node"]["name"],
                            "tagline": e["node"]["tagline"],
                            "votes": e["node"]["votesCount"],
                            "url": e["node"].get("website", ""),
                            "topics": [
                                t["node"]["name"]
                                for t in e["node"].get("topics", {}).get("edges", [])
                            ],
                        }
                        for e in edges
                    ],
                    "count": len(edges),
                }
            return {
                "success": False,
                "error": f"Product Hunt API HTTP {res.status_code}",
                "products": [],
            }
        except Exception as exc:
            return {"success": False, "error": str(exc), "products": []}

    async def get_trending_news(
        self,
        query: str = "make money online digital business AI",
        language: str = "en",
        limit: int = 15,
    ) -> dict[str, Any]:
        """
        Noticias en tiempo real via NewsAPI.
        Requiere NEWS_API_KEY.
        """
        if not getattr(settings, "NEWS_API_KEY", None):
            return {
                "success": False,
                "error": "NEWS_API_KEY no configurado",
                "articles": [],
            }
        try:
            res = await self._http.get(
                "https://newsapi.org/v2/everything",
                params={
                    "q": query,
                    "language": language,
                    "sortBy": "publishedAt",
                    "pageSize": limit,
                    "apiKey": settings.NEWS_API_KEY,
                },
            )
            if res.status_code == 200:
                articles = res.json().get("articles", [])
                return {
                    "success": True,
                    "source": "newsapi",
                    "articles": [
                        {
                            "title": a.get("title", ""),
                            "description": a.get("description", ""),
                            "url": a.get("url", ""),
                            "source": a.get("source", {}).get("name", ""),
                            "published_at": a.get("publishedAt", ""),
                        }
                        for a in articles
                        if a.get("title") and "[Removed]" not in a.get("title", "")
                    ],
                }
            return {
                "success": False,
                "error": f"NewsAPI HTTP {res.status_code}: {res.text[:200]}",
                "articles": [],
            }
        except Exception as exc:
            return {"success": False, "error": str(exc), "articles": []}

    # ══════════════════════════════════════════════════════════════
    # INTELIGENCIA DE MERCADO AGREGADA
    # ══════════════════════════════════════════════════════════════

    async def gather_market_intelligence(
        self,
        focus: str = "digital products passive income AI tools",
    ) -> dict[str, Any]:
        """
        Recopila inteligencia de mercado real de multiples fuentes en paralelo.
        Retorna datos consolidados listos para que la IA genere un plan de accion.
        """
        logger.info("[WebTools] Recopilando inteligencia de mercado...")

        hn, reddit, news, search = await asyncio.gather(
            self.get_hacker_news_trending(limit=15),
            self.get_reddit_trending(limit=15),
            self.get_trending_news(query=focus + " 2025", limit=10),
            self.search_web(f"best digital products to sell online 2025 {focus}", num_results=8),
            return_exceptions=True,
        )

        intelligence: dict[str, Any] = {"focus": focus, "sources_available": []}

        if isinstance(hn, dict) and hn.get("success"):
            intelligence["hacker_news"] = hn["stories"][:10]
            intelligence["sources_available"].append("hacker_news")

        if isinstance(reddit, dict) and reddit.get("success"):
            intelligence["reddit"] = reddit["posts"][:10]
            intelligence["sources_available"].append("reddit")

        if isinstance(news, dict) and news.get("success"):
            intelligence["news"] = news["articles"][:8]
            intelligence["sources_available"].append("newsapi")

        if isinstance(search, dict) and search.get("success"):
            intelligence["web_search"] = search["results"][:6]
            intelligence["sources_available"].append(f"web_{search.get('source', 'search')}")

        # Extraer trending keywords de todas las fuentes
        all_titles = []
        for item in intelligence.get("hacker_news", []):
            all_titles.append(item.get("title", ""))
        for item in intelligence.get("reddit", []):
            all_titles.append(item.get("title", ""))
        for item in intelligence.get("news", []):
            all_titles.append(item.get("title", ""))

        intelligence["trending_titles"] = all_titles[:20]
        intelligence["total_data_points"] = len(all_titles)
        intelligence["sources_count"] = len(intelligence["sources_available"])

        logger.info(
            "[WebTools] Inteligencia recopilada: %d fuentes, %d datos",
            intelligence["sources_count"],
            intelligence["total_data_points"],
        )
        return intelligence

    async def research_niche(self, niche: str) -> dict[str, Any]:
        """
        Investiga un nicho especifico: busca en Google, Reddit, HN y noticias.
        Retorna datos reales para que la IA evalue el potencial de monetizacion.
        """
        web, reddit_niche, news_niche = await asyncio.gather(
            self.search_web(f"{niche} make money 2025 opportunities", num_results=8),
            self.get_reddit_trending(
                subreddits=[niche.replace(" ", ""), "entrepreneur", "SideProject"]
            ),
            self.get_trending_news(query=f"{niche} business revenue 2025", limit=8),
            return_exceptions=True,
        )

        result: dict[str, Any] = {"niche": niche, "data": {}}

        if isinstance(web, dict) and web.get("success"):
            result["data"]["web_results"] = web["results"]
        if isinstance(reddit_niche, dict) and reddit_niche.get("success"):
            result["data"]["reddit_posts"] = reddit_niche["posts"][:8]
        if isinstance(news_niche, dict) and news_niche.get("success"):
            result["data"]["news"] = news_niche["articles"][:6]

        result["success"] = bool(result["data"])
        if not result["success"]:
            result["error"] = "Ninguna fuente retorno datos — verifica conectividad"
        return result
