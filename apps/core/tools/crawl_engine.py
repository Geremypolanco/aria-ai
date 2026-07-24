"""
crawl_engine.py — Web Intelligence engine for ARIA AI.

Integrates Crawl4AI and Firecrawl for advanced capabilities:
  - Asynchronous, structured scraping (Crawl4AI)
  - Converting websites into clean data (Firecrawl)
  - Competitor analysis with content extraction
  - Site mapping for SEO audits
  - Data extraction for Revenue Attribution

Complements web_tools.py with professional-grade scraping capabilities.

Reference:
  - Crawl4AI: https://github.com/unclecode/crawl4ai
  - Firecrawl: https://github.com/firecrawl/firecrawl
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any
from urllib.parse import urlparse

logger = logging.getLogger("aria.crawl_engine")

# ── Crawl4AI import with fallback ────────────────────────────────────────────
try:
    from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig
    from crawl4ai.extraction_strategy import (  # noqa: F401
        JsonCssExtractionStrategy,
        LLMExtractionStrategy,
    )

    CRAWL4AI_AVAILABLE = True
    logger.info("[Crawl4AI] Library loaded successfully.")
except ImportError:
    CRAWL4AI_AVAILABLE = False
    logger.warning(
        "[Crawl4AI] crawl4ai not installed. "
        "Using httpx as a fallback. "
        "Install with: pip install crawl4ai"
    )
    AsyncWebCrawler = None  # type: ignore[assignment,misc]
    BrowserConfig = None  # type: ignore[assignment,misc]
    CrawlerRunConfig = None  # type: ignore[assignment,misc]

# ── Firecrawl import with fallback ───────────────────────────────────────────
try:
    from firecrawl import FirecrawlApp

    FIRECRAWL_AVAILABLE = True
    logger.info("[Firecrawl] Library loaded successfully.")
except ImportError:
    FIRECRAWL_AVAILABLE = False
    logger.warning(
        "[Firecrawl] firecrawl-py not installed. "
        "Using httpx as a fallback. "
        "Install with: pip install firecrawl-py"
    )
    FirecrawlApp = None  # type: ignore[assignment,misc]


# ── Data Models ───────────────────────────────────────────────────────────────


class CrawlResult:
    """Standardized result of a crawl."""

    def __init__(
        self,
        url: str,
        markdown: str = "",
        html: str = "",
        text: str = "",
        metadata: dict[str, Any] | None = None,
        links: list[str] | None = None,
        success: bool = True,
        error: str = "",
        source: str = "unknown",
    ) -> None:
        self.url = url
        self.markdown = markdown
        self.html = html
        self.text = text
        self.metadata = metadata or {}
        self.links = links or []
        self.success = success
        self.error = error
        self.source = source  # "crawl4ai", "firecrawl", "httpx_fallback"

    def to_dict(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "markdown": self.markdown[:5000] if self.markdown else "",
            "text": self.text[:3000] if self.text else "",
            "metadata": self.metadata,
            "links_count": len(self.links),
            "success": self.success,
            "error": self.error,
            "source": self.source,
        }


# ── Crawling Engine with Crawl4AI ────────────────────────────────────────────


class Crawl4AIEngine:
    """
    Asynchronous scraping engine with Crawl4AI.

    Ideal for:
    - Competitor analysis (extracts clean content)
    - Structured scraping with LLM extraction
    - Data extraction from dynamic (JS) pages
    - Batch processing of multiple URLs
    """

    async def crawl_url(
        self,
        url: str,
        extract_schema: dict[str, Any] | None = None,
        use_llm_extraction: bool = False,
    ) -> CrawlResult:
        """
        Crawls a URL and extracts clean content.

        Args:
            url: URL to crawl
            extract_schema: CSS schema for structured extraction
            use_llm_extraction: Whether to use an LLM for smart extraction

        Returns:
            CrawlResult with markdown, text, and metadata
        """
        if not CRAWL4AI_AVAILABLE:
            return await self._httpx_fallback(url)

        try:
            config = CrawlerRunConfig(
                word_count_threshold=10,
                remove_overlay_elements=True,
                process_iframes=False,
            )

            if extract_schema:
                config.extraction_strategy = JsonCssExtractionStrategy(schema=extract_schema)

            async with AsyncWebCrawler() as crawler:
                result = await crawler.arun(url=url, config=config)

                if result.success:
                    return CrawlResult(
                        url=url,
                        markdown=result.markdown or "",
                        html=result.html or "",
                        text=result.text or "",
                        metadata=result.metadata or {},
                        links=(
                            result.links.get("internal", []) + result.links.get("external", [])
                            if hasattr(result, "links") and result.links
                            else []
                        ),
                        success=True,
                        source="crawl4ai",
                    )
                logger.warning("[Crawl4AI] Crawl failed for %s: %s", url, result.error_message)
                return await self._httpx_fallback(url)

        except Exception as exc:
            logger.error("[Crawl4AI] Error crawling %s: %s", url, exc)
            return await self._httpx_fallback(url)

    async def crawl_competitor(
        self,
        competitor_url: str,
        extract_pricing: bool = True,
        extract_features: bool = True,
    ) -> dict[str, Any]:
        """
        Analyzes a competitor site, extracting key information.

        Args:
            competitor_url: Competitor URL
            extract_pricing: Whether to extract pricing information
            extract_features: Whether to extract product features

        Returns:
            Structured analysis of the competitor
        """
        result = await self.crawl_url(competitor_url)

        analysis = {
            "url": competitor_url,
            "domain": urlparse(competitor_url).netloc,
            "content_preview": result.markdown[:2000] if result.markdown else "",
            "success": result.success,
            "source": result.source,
        }

        if result.success and result.markdown:
            # Extract key information from the content
            content_lower = result.markdown.lower()

            # Detect prices
            # NOTE: pattern intentionally matches both English and Spanish
            # unit suffixes (mo/month/yr/year vs. mes/año) since scraped
            # pages may be in either language — do not translate the pattern.
            if extract_pricing:
                import re

                prices = re.findall(
                    r"\$[\d,]+(?:\.\d{2})?(?:/(?:mo|month|yr|year|mes|año))?", result.markdown
                )
                analysis["detected_prices"] = prices[:10]

            # Detect features
            # NOTE: keyword list intentionally mixes English and Spanish
            # terms since scraped pages may be in either language — do not
            # translate the keyword values themselves.
            if extract_features:
                features = []
                for line in result.markdown.split("\n"):
                    if any(
                        kw in line.lower()
                        for kw in ["feature", "include", "benefit", "característica"]
                    ):
                        if len(line) > 10:
                            features.append(line.strip())
                analysis["detected_features"] = features[:10]

            # Detect technologies
            tech_keywords = ["react", "vue", "angular", "shopify", "wordpress", "stripe", "paypal"]
            analysis["detected_tech"] = [tech for tech in tech_keywords if tech in content_lower]

        return analysis

    async def batch_crawl(
        self,
        urls: list[str],
        max_concurrent: int = 5,
    ) -> list[CrawlResult]:
        """
        Crawls multiple URLs in parallel.

        Args:
            urls: List of URLs to crawl
            max_concurrent: Maximum simultaneous crawls

        Returns:
            List of CrawlResults
        """
        semaphore = asyncio.Semaphore(max_concurrent)

        async def crawl_with_semaphore(url: str) -> CrawlResult:
            async with semaphore:
                return await self.crawl_url(url)

        results = await asyncio.gather(
            *[crawl_with_semaphore(url) for url in urls],
            return_exceptions=False,
        )
        return list(results)

    async def _httpx_fallback(self, url: str) -> CrawlResult:
        """Fallback using httpx when Crawl4AI is not available."""
        try:
            import httpx
            from bs4 import BeautifulSoup

            async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
                response = await client.get(
                    url,
                    headers={"User-Agent": "Mozilla/5.0 (compatible; AriaBot/1.0)"},
                )
                response.raise_for_status()

                soup = BeautifulSoup(response.text, "html.parser")
                # Remove scripts and styles
                for tag in soup(["script", "style", "nav", "footer"]):
                    tag.decompose()

                text = soup.get_text(separator="\n", strip=True)
                links = [a.get("href", "") for a in soup.find_all("a", href=True)]

                return CrawlResult(
                    url=url,
                    text=text[:5000],
                    markdown=text[:5000],
                    links=[l for l in links if l.startswith("http")][:20],
                    success=True,
                    source="httpx_fallback",
                )

        except Exception as exc:
            return CrawlResult(
                url=url,
                success=False,
                error=str(exc),
                source="httpx_fallback",
            )


# ── Firecrawl Conversion Engine ──────────────────────────────────────────────


class FirecrawlEngine:
    """
    Web-to-data conversion engine with Firecrawl.

    Ideal for:
    - Converting entire websites into structured data
    - Mapping sites for SEO audits
    - Automatically analyzing businesses
    - Extracting data from authenticated sites
    """

    def __init__(self, api_key: str = "") -> None:
        self._api_key = api_key
        self._app: Any = None

        if FIRECRAWL_AVAILABLE and api_key:
            try:
                self._app = FirecrawlApp(api_key=api_key)
                logger.info("[Firecrawl] App initialized successfully")
            except Exception as exc:
                logger.warning("[Firecrawl] Initialization error: %s", exc)

    def _is_available(self) -> bool:
        return self._app is not None

    async def scrape_url(
        self,
        url: str,
        formats: list[str] | None = None,
    ) -> CrawlResult:
        """
        Converts a URL into clean data with Firecrawl.

        Args:
            url: URL to scrape
            formats: Output formats ['markdown', 'html', 'links', 'screenshot']

        Returns:
            CrawlResult with the structured content
        """
        if not self._is_available():
            logger.info("[Firecrawl] Not available, using Crawl4AI as a fallback")
            crawl4ai = Crawl4AIEngine()
            return await crawl4ai.crawl_url(url)

        try:
            formats = formats or ["markdown", "links"]
            result = self._app.scrape_url(url, params={"formats": formats})

            if result and result.get("success"):
                return CrawlResult(
                    url=url,
                    markdown=result.get("markdown", ""),
                    html=result.get("html", ""),
                    metadata=result.get("metadata", {}),
                    links=[l.get("url", "") for l in result.get("links", [])],
                    success=True,
                    source="firecrawl",
                )
            logger.warning("[Firecrawl] Scrape failed for %s", url)
            crawl4ai = Crawl4AIEngine()
            return await crawl4ai.crawl_url(url)

        except Exception as exc:
            logger.error("[Firecrawl] Error scraping %s: %s", url, exc)
            crawl4ai = Crawl4AIEngine()
            return await crawl4ai.crawl_url(url)

    async def map_site(
        self,
        url: str,
        limit: int = 50,
    ) -> dict[str, Any]:
        """
        Maps all URLs of a website.
        Useful for SEO audits and competitor structure analysis.

        Args:
            url: Site root URL
            limit: Maximum URLs to map

        Returns:
            Site map with URLs and metadata
        """
        if not self._is_available():
            # Fallback: crawl the main page and extract links
            crawl4ai = Crawl4AIEngine()
            result = await crawl4ai.crawl_url(url)
            return {
                "url": url,
                "links": result.links[:limit],
                "total_pages": len(result.links),
                "source": "crawl4ai_fallback",
            }

        try:
            result = self._app.map_url(url, params={"limit": limit})
            return {
                "url": url,
                "links": result.get("links", [])[:limit],
                "total_pages": len(result.get("links", [])),
                "source": "firecrawl",
            }
        except Exception as exc:
            logger.error("[Firecrawl] Error mapping %s: %s", url, exc)
            return {"url": url, "links": [], "error": str(exc), "source": "firecrawl"}

    async def crawl_site(
        self,
        url: str,
        limit: int = 10,
        include_paths: list[str] | None = None,
    ) -> list[CrawlResult]:
        """
        Crawls a full site with Firecrawl.

        Args:
            url: Root URL
            limit: Maximum pages
            include_paths: Specific paths to include (e.g. ['/pricing', '/features'])

        Returns:
            List of CrawlResults for each page
        """
        if not self._is_available():
            crawl4ai = Crawl4AIEngine()
            return await crawl4ai.batch_crawl([url])

        try:
            params: dict[str, Any] = {"limit": limit, "formats": ["markdown"]}
            if include_paths:
                params["includePaths"] = include_paths

            result = self._app.crawl_url(url, params=params)
            pages = result.get("data", []) if isinstance(result, dict) else []

            return [
                CrawlResult(
                    url=page.get("metadata", {}).get("url", url),
                    markdown=page.get("markdown", ""),
                    metadata=page.get("metadata", {}),
                    success=True,
                    source="firecrawl",
                )
                for page in pages
            ]

        except Exception as exc:
            logger.error("[Firecrawl] Error crawling site %s: %s", url, exc)
            return []

    async def analyze_business(
        self,
        business_url: str,
    ) -> dict[str, Any]:
        """
        Automatically analyzes a business, extracting key information.
        Integrates with Aria's MarketingAgent and CFO Agent.

        Args:
            business_url: URL of the business to analyze

        Returns:
            Complete business analysis
        """
        # Scrape the main page
        main_page = await self.scrape_url(business_url)

        # Try key pages
        f"{urlparse(business_url).scheme}://{urlparse(business_url).netloc}"

        analysis = {
            "url": business_url,
            "domain": urlparse(business_url).netloc,
            "main_content": main_page.markdown[:3000] if main_page.markdown else "",
            "success": main_page.success,
            "source": main_page.source,
        }

        # Map site for structure
        site_map = await self.map_site(business_url, limit=20)
        analysis["site_structure"] = {
            "total_pages": site_map.get("total_pages", 0),
            "sample_urls": site_map.get("links", [])[:10],
        }

        return analysis


# ── Unified Market Intelligence Engine ───────────────────────────────────────


class MarketIntelligenceEngine:
    """
    Unified Market Intelligence engine for ARIA AI.

    Combines Crawl4AI (asynchronous scraping) and Firecrawl (web-to-data conversion)
    to provide complete market analysis capabilities.

    Integrates with:
    - web_tools.py (existing web search)
    - market_tools.py (existing market analysis)
    - MarketingAgent (trend analysis)
    - CFO Agent (competitor analysis)
    """

    def __init__(self, firecrawl_api_key: str = "") -> None:
        self.crawl4ai = Crawl4AIEngine()
        self.firecrawl = FirecrawlEngine(api_key=firecrawl_api_key)

    async def analyze_competitors(
        self,
        competitor_urls: list[str],
        niche: str = "",
    ) -> dict[str, Any]:
        """
        Analyzes multiple competitors in parallel.

        Args:
            competitor_urls: List of competitor URLs
            niche: Market niche for context

        Returns:
            Comparative competitor analysis
        """
        logger.info("[MarketIntelligence] Analyzing %d competitors", len(competitor_urls))

        # Crawl all in parallel with Crawl4AI
        tasks = [self.crawl4ai.crawl_competitor(url) for url in competitor_urls]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        competitors = []
        for url, result in zip(competitor_urls, results, strict=False):
            if isinstance(result, Exception):
                competitors.append({"url": url, "error": str(result), "success": False})
            else:
                competitors.append(result)

        return {
            "niche": niche,
            "competitors_analyzed": len(competitors),
            "competitors": competitors,
            "crawl4ai_available": CRAWL4AI_AVAILABLE,
            "firecrawl_available": FIRECRAWL_AVAILABLE,
        }

    async def extract_market_data(
        self,
        url: str,
        data_type: str = "general",
    ) -> dict[str, Any]:
        """
        Extracts market data from a specific URL.

        Args:
            url: URL to analyze
            data_type: Data type ('pricing', 'features', 'reviews', 'general')

        Returns:
            Structured market data
        """
        # Use Firecrawl if available (better quality), otherwise Crawl4AI
        if self.firecrawl._is_available():
            result = await self.firecrawl.scrape_url(url)
        else:
            result = await self.crawl4ai.crawl_url(url)

        return {
            "url": url,
            "data_type": data_type,
            "content": result.markdown[:4000] if result.markdown else result.text[:4000],
            "success": result.success,
            "source": result.source,
        }

    async def seo_audit(
        self,
        url: str,
    ) -> dict[str, Any]:
        """
        Basic SEO audit of a website.

        Args:
            url: URL of the site to audit

        Returns:
            SEO report with structure, links, and metadata
        """
        # Map site with Firecrawl
        site_map = await self.firecrawl.map_site(url, limit=100)

        # Crawl main page for metadata
        main_page = await self.crawl4ai.crawl_url(url)

        return {
            "url": url,
            "total_pages": site_map.get("total_pages", 0),
            "pages_sample": site_map.get("links", [])[:20],
            "main_page_content_length": len(main_page.markdown or ""),
            "external_links": len(
                [l for l in main_page.links if urlparse(l).netloc != urlparse(url).netloc]
            ),
            "internal_links": len(
                [l for l in main_page.links if urlparse(l).netloc == urlparse(url).netloc]
            ),
            "source": main_page.source,
        }


# ── Singleton ────────────────────────────────────────────────────────────────
_engine_instance: MarketIntelligenceEngine | None = None


def get_market_intelligence_engine() -> MarketIntelligenceEngine:
    """Returns the Market Intelligence engine singleton."""
    global _engine_instance
    if _engine_instance is None:
        import os

        _engine_instance = MarketIntelligenceEngine(
            firecrawl_api_key=os.getenv("FIRECRAWL_API_KEY", ""),
        )
    return _engine_instance
