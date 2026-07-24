"""
web_tools.py — Real Internet access for ARIA AI.

ARIA can browse and extract information from the internet using:
  1. SerpAPI — real Google Search (SERP_API_KEY)
  2. DuckDuckGo Instant Answer API — free search, no key needed
  3. Hacker News API — trending tech, no auth needed
  4. Reddit API — subreddit search, no auth needed
  5. Product Hunt trending — via public GraphQL
  6. httpx — fetch any public URL
  7. NewsAPI — real-time news (NEWS_API_KEY)
  8. Clean text extraction from web pages

Principle: REAL internet access. No made-up data.
If a source fails, try the next one — always report which ones worked.
"""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import os
import re
import socket
import uuid
from datetime import datetime
from typing import Any
from urllib.parse import urlparse

import httpx

from apps.core.config import settings

logger = logging.getLogger("aria.web_tools")


async def _assert_public_url(url: str) -> None:
    """SSRF guard for fetch_page(): the target URL comes from the LLM's tool
    call, ultimately steerable by whatever the user asks ARIA to fetch. Without
    this, a prompt like "fetch http://169.254.169.254/... and tell me what it
    says" makes the *server* issue that request — reachable internal services,
    cloud metadata endpoints, etc. Raises ValueError if the URL isn't safe to
    fetch; caller (fetch_page) turns that into a normal error result.
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"unsupported URL scheme: {parsed.scheme!r}")
    host = parsed.hostname
    if not host:
        raise ValueError("URL has no host")
    try:
        infos = await asyncio.to_thread(socket.getaddrinfo, host, None)
    except socket.gaierror as exc:
        raise ValueError(f"could not resolve host: {exc}") from exc
    for info in infos:
        addr = info[4][0]
        ip = ipaddress.ip_address(addr)
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        ):
            raise ValueError(f"refusing to fetch a non-public address ({addr})")


class WebTools:
    """
    Real internet access for ARIA AI.
    Searches, reads, and extracts information from any public source.
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
    # WEB SEARCH
    # ══════════════════════════════════════════════════════════════

    async def search_web(self, query: str, num_results: int = 10) -> dict[str, Any]:
        """
        Real web search with smart query expansion.
        Tries SerpAPI first (best quality), then DuckDuckGo + NewsAPI.
        """
        optimized_query = self._optimize_query(query)
        if optimized_query != query:
            logger.info("[WebTools] Optimized query: %s -> %s", query, optimized_query)

        # 1. SerpAPI (if configured and within quota) — real Google
        if getattr(settings, "SERP_API_KEY", None):
            result = await self._search_serpapi(optimized_query, num_results)
            if result["success"] and result.get("results"):
                return result

        # 2. Tavily — web search built for AI, reliable from servers (if key set)
        if getattr(settings, "TAVILY_API_KEY", None):
            result = await self._search_tavily(optimized_query, num_results)
            if result["success"] and result.get("results"):
                return result

        # 3. Brave Search — general, reliable from datacenters (if key set)
        if getattr(settings, "BRAVE_API_KEY", None):
            result = await self._search_brave(optimized_query, num_results)
            if result["success"] and result.get("results"):
                return result

        # 4. NewsAPI — current news (if NEWS_API_KEY is set)
        if getattr(settings, "NEWS_API_KEY", None):
            result = await self._search_newsapi(query, num_results)
            if result["success"] and result.get("results"):
                return result

        # 5. Wikipedia — factual/encyclopedic, NO key needed, reliable from servers
        result = await self._search_wikipedia(optimized_query, num_results)
        if result["success"] and result.get("results"):
            return result

        # 6. DuckDuckGo Instant Answer — direct answers, no key needed
        result = await self._search_duckduckgo(optimized_query)
        if result["success"] and result.get("results"):
            return result

        return {
            "success": False,
            "error": "All search sources failed",
            "results": [],
            "query": query,
        }

    def _optimize_query(self, query: str) -> str:
        """Optimizes the query for better results based on search type.

        NOTE: the keyword-matching lists and appended suffixes below are
        intentionally bilingual (Spanish + English) so both Spanish- and
        English-language queries get the same optimization — left untouched
        by design, not an oversight.
        """
        q = query.strip()
        words = q.split()
        # Don't modify queries that are already specific (> 6 words)
        if len(words) > 6:
            return q
        q_lower = q.lower()
        # Business and monetization
        if any(w in q_lower for w in ["vender", "negocio", "shopify", "ecommerce", "tienda"]):
            return f"{q} estrategia 2025 guía completa"
        # "How to" questions
        if q_lower.startswith(("cómo", "como", "how to", "how do")):
            return f"{q} paso a paso tutorial 2025"
        # Trends and news
        if any(w in q_lower for w in ["tendencia", "trend", "nuevo", "latest", "mejor"]):
            return f"{q} 2025 actualizado"
        # Marketing and content
        if any(w in q_lower for w in ["marketing", "seo", "contenido", "social media"]):
            return f"{q} mejores prácticas ejemplos 2025"
        # AI and technology
        if any(w in q_lower for w in ["ai", "ia", "inteligencia artificial", "llm", "gpt"]):
            return f"{q} 2025 comparison review"
        return q

    async def _search_serpapi(self, query: str, num: int = 10) -> dict[str, Any]:
        """Search via SerpAPI — real Google results."""
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
        Search via the DuckDuckGo Instant Answer API.
        Completely free, no API key needed, always available.
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
                # Abstract (main result)
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

    async def _search_tavily(self, query: str, num: int = 10) -> dict[str, Any]:
        """Tavily — AI-oriented web search. Free tier, works from servers.
        Alternative to SerpAPI when it is out of quota (set TAVILY_API_KEY)."""
        key = getattr(settings, "TAVILY_API_KEY", None)
        if not key:
            return {"success": False, "results": [], "source": "tavily"}
        try:
            res = await self._http.post(
                "https://api.tavily.com/search",
                json={
                    "api_key": key,
                    "query": query,
                    "max_results": min(num, 10),
                    "search_depth": "basic",
                },
            )
            if res.status_code == 200:
                data = res.json()
                results = [
                    {
                        "title": r.get("title", ""),
                        "url": r.get("url", ""),
                        "snippet": (r.get("content", "") or "")[:300],
                        "source": "Tavily",
                    }
                    for r in (data.get("results") or [])[:num]
                ]
                if results:
                    return {
                        "success": True,
                        "source": "tavily",
                        "query": query,
                        "results": results,
                    }
        except Exception as exc:
            logger.error("[WebTools] tavily error: %s", exc)
        return {"success": False, "results": [], "source": "tavily"}

    async def _search_brave(self, query: str, num: int = 10) -> dict[str, Any]:
        """Brave Search API — reliable general web search from datacenters.
        Free tier available (set BRAVE_API_KEY)."""
        key = getattr(settings, "BRAVE_API_KEY", None)
        if not key:
            return {"success": False, "results": [], "source": "brave"}
        try:
            res = await self._http.get(
                "https://api.search.brave.com/res/v1/web/search",
                params={"q": query, "count": min(num, 20)},
                headers={"X-Subscription-Token": key, "Accept": "application/json"},
            )
            if res.status_code == 200:
                web = (res.json().get("web") or {}).get("results") or []
                results = [
                    {
                        "title": w.get("title", ""),
                        "url": w.get("url", ""),
                        "snippet": (w.get("description", "") or "")[:300],
                        "source": "Brave",
                    }
                    for w in web[:num]
                ]
                if results:
                    return {
                        "success": True,
                        "source": "brave",
                        "query": query,
                        "results": results,
                    }
        except Exception as exc:
            logger.error("[WebTools] brave error: %s", exc)
        return {"success": False, "results": [], "source": "brave"}

    async def _search_wikipedia(self, query: str, num: int = 6) -> dict[str, Any]:
        """Wikipedia search — keyless, reliable from servers. Good for factual /
        encyclopedic queries; a real fallback that never needs quota."""
        try:
            res = await self._http.get(
                "https://en.wikipedia.org/w/api.php",
                params={
                    "action": "query",
                    "list": "search",
                    "srsearch": query,
                    "format": "json",
                    "srlimit": min(num, 8),
                },
            )
            if res.status_code == 200:
                hits = (res.json().get("query") or {}).get("search") or []
                results = []
                for h in hits[:num]:
                    title = h.get("title", "")
                    snippet = re.sub(r"<[^>]+>", "", h.get("snippet", "") or "")
                    slug = title.replace(" ", "_")
                    results.append(
                        {
                            "title": title,
                            "url": f"https://en.wikipedia.org/wiki/{slug}",
                            "snippet": snippet[:300],
                            "source": "Wikipedia",
                        }
                    )
                if results:
                    return {
                        "success": True,
                        "source": "wikipedia",
                        "query": query,
                        "results": results,
                    }
        except Exception as exc:
            logger.error("[WebTools] wikipedia error: %s", exc)
        return {"success": False, "results": [], "source": "wikipedia"}

    # ══════════════════════════════════════════════════════════════
    # SCREENSHOTS AND REAL NAVIGATION
    # ══════════════════════════════════════════════════════════════

    async def take_screenshot(self, url: str, full_page: bool = False) -> dict[str, Any]:
        """
        Takes a real screenshot of any URL using Playwright.
        Returns the local path of the generated file.
        """
        try:
            await _assert_public_url(url)

            from playwright.async_api import async_playwright

            # Create the screenshots directory if it doesn't exist
            os.makedirs("screenshots", exist_ok=True)
            filename = f"screenshots/{uuid.uuid4().short if hasattr(uuid.uuid4(), 'short') else str(uuid.uuid4())[:8]}_{int(datetime.now().timestamp())}.png"

            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                context = await browser.new_context(
                    viewport={"width": 1280, "height": 800},
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                )
                page = await context.new_page()

                logger.info("[WebTools] Navigating for screenshot: %s", url)
                await page.goto(url, wait_until="networkidle", timeout=30000)

                # Wait a bit longer in case there are animations
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
            logger.error("[WebTools] Error taking screenshot of %s: %s", url, exc)
            return {"success": False, "error": str(exc), "url": url}

    async def _search_newsapi(self, query: str, num: int = 10) -> dict[str, Any]:
        """News search via NewsAPI (fallback using NEWS_API_KEY)."""
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
                            "snippet": a.get("description") or (a.get("content") or "")[:300],
                            "published": a.get("publishedAt", ""),
                        }
                        for a in articles[:num]
                    ],
                }
        except Exception as exc:
            logger.error("[WebTools] newsapi error: %s", exc)
        return {"success": False, "results": [], "source": "newsapi"}

    # ══════════════════════════════════════════════════════════════
    # WEB PAGE FETCHING
    # ══════════════════════════════════════════════════════════════

    async def fetch_page(self, url: str, max_chars: int = 5000) -> dict[str, Any]:
        """
        Downloads and extracts clean text from any public URL.
        Removes HTML, scripts, styles, nav, footer — returns readable content.
        """
        try:
            # Re-validated on every hop (redirects disabled here on purpose) —
            # a URL that resolves to something public can still redirect to an
            # internal address, and that would silently bypass a check that
            # only ran once against the original URL.
            next_url = url
            res = None
            for _hop in range(5):
                await _assert_public_url(next_url)
                res = await self._http.get(next_url, timeout=15.0, follow_redirects=False)
                if res.is_redirect:
                    next_url = str(res.next_request.url)
                    continue
                break
            else:
                return {"success": False, "error": "too many redirects", "url": url}

            if res.status_code != 200:
                return {"success": False, "error": f"HTTP {res.status_code}", "url": url}

            html = res.text

            # Extract title
            title_match = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
            title = re.sub(r"\s+", " ", title_match.group(1)).strip() if title_match else ""

            # Remove noise: scripts, styles, nav, footer, header, aside, forms
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

            # Convert content blocks to readable text
            text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
            text = re.sub(r"<p[^>]*>", "\n", text, flags=re.IGNORECASE)
            text = re.sub(r"<h[1-6][^>]*>", "\n## ", text, flags=re.IGNORECASE)
            text = re.sub(r"</h[1-6]>", "\n", text, flags=re.IGNORECASE)
            text = re.sub(r"<li[^>]*>", "\n- ", text, flags=re.IGNORECASE)

            # Remove remaining HTML tags
            text = re.sub(r"<[^>]+>", " ", text)

            # Decode common HTML entities
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

            # Clean up multiple spaces but preserve useful line breaks
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
    # TREND SOURCES (all free, no key needed)
    # ══════════════════════════════════════════════════════════════

    async def get_hacker_news_trending(self, limit: int = 20) -> dict[str, Any]:
        """
        Real-time top stories from Hacker News.
        No API key needed. Very reliable source of tech trends.
        """
        try:
            # Get top story IDs
            ids_res = await self._http.get("https://hacker-news.firebaseio.com/v0/topstories.json")
            if ids_res.status_code != 200:
                return {"success": False, "error": f"HN API HTTP {ids_res.status_code}"}

            ids = ids_res.json()[:limit]

            # Fetch stories in parallel
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
        Trending Reddit posts (no auth, using public JSON).
        Default subreddits: the most relevant ones for digital business.
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
        Trending products from Product Hunt via the public API.
        Requires PRODUCT_HUNT_TOKEN (free with an account).
        Without a token: returns an explicit error.
        """
        token = getattr(settings, "PRODUCT_HUNT_TOKEN", None)
        if not token:
            return {
                "success": False,
                "error": "PRODUCT_HUNT_TOKEN not configured. Create an account at producthunt.com/v2/oauth/applications",
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
        Real-time news via NewsAPI.
        Requires NEWS_API_KEY.
        """
        if not getattr(settings, "NEWS_API_KEY", None):
            return {
                "success": False,
                "error": "NEWS_API_KEY not configured",
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
    # AGGREGATED MARKET INTELLIGENCE
    # ══════════════════════════════════════════════════════════════

    async def gather_market_intelligence(
        self,
        focus: str = "digital products passive income AI tools",
    ) -> dict[str, Any]:
        """
        Gathers real market intelligence from multiple sources in parallel.
        Returns consolidated data ready for the AI to generate an action plan.
        """
        logger.info("[WebTools] Gathering market intelligence...")

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

        # Extract trending keywords from all sources
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
            "[WebTools] Intelligence gathered: %d sources, %d data points",
            intelligence["sources_count"],
            intelligence["total_data_points"],
        )
        return intelligence

    async def research_niche(self, niche: str) -> dict[str, Any]:
        """
        Researches a specific niche: searches Google, Reddit, HN, and news.
        Returns real data for the AI to evaluate monetization potential.
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
            result["error"] = "No source returned data — check connectivity"
        return result
