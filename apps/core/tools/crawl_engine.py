"""
crawl_engine.py — Motor de Web Intelligence para ARIA AI.

Integra Crawl4AI y Firecrawl para capacidades avanzadas de:
  - Scraping asíncrono y estructurado (Crawl4AI)
  - Conversión de webs a datos limpios (Firecrawl)
  - Análisis de competidores con extracción de contenido
  - Mapeo de sitios para auditorías SEO
  - Extracción de datos para Revenue Attribution

Complementa web_tools.py con capacidades de scraping de nivel profesional.

Referencia:
  - Crawl4AI: https://github.com/unclecode/crawl4ai
  - Firecrawl: https://github.com/firecrawl/firecrawl
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any
from urllib.parse import urlparse

logger = logging.getLogger("aria.crawl_engine")

# ── Crawl4AI Import con fallback ─────────────────────────────────────────────
try:
    from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig
    from crawl4ai.extraction_strategy import (  # noqa: F401
        JsonCssExtractionStrategy,
        LLMExtractionStrategy,
    )

    CRAWL4AI_AVAILABLE = True
    logger.info("[Crawl4AI] Librería cargada correctamente.")
except ImportError:
    CRAWL4AI_AVAILABLE = False
    logger.warning(
        "[Crawl4AI] crawl4ai no instalado. "
        "Usando httpx como fallback. "
        "Instala con: pip install crawl4ai"
    )
    AsyncWebCrawler = None  # type: ignore[assignment,misc]
    BrowserConfig = None  # type: ignore[assignment,misc]
    CrawlerRunConfig = None  # type: ignore[assignment,misc]

# ── Firecrawl Import con fallback ────────────────────────────────────────────
try:
    from firecrawl import FirecrawlApp

    FIRECRAWL_AVAILABLE = True
    logger.info("[Firecrawl] Librería cargada correctamente.")
except ImportError:
    FIRECRAWL_AVAILABLE = False
    logger.warning(
        "[Firecrawl] firecrawl-py no instalado. "
        "Usando httpx como fallback. "
        "Instala con: pip install firecrawl-py"
    )
    FirecrawlApp = None  # type: ignore[assignment,misc]


# ── Modelos de Datos ─────────────────────────────────────────────────────────


class CrawlResult:
    """Resultado estandarizado de un crawl."""

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


# ── Motor de Crawling con Crawl4AI ───────────────────────────────────────────


class Crawl4AIEngine:
    """
    Motor de scraping asíncrono con Crawl4AI.

    Ideal para:
    - Análisis de competidores (extrae contenido limpio)
    - Scraping estructurado con extracción LLM
    - Extracción de datos de páginas dinámicas (JS)
    - Procesamiento en batch de múltiples URLs
    """

    async def crawl_url(
        self,
        url: str,
        extract_schema: dict[str, Any] | None = None,
        use_llm_extraction: bool = False,
    ) -> CrawlResult:
        """
        Crawlea una URL y extrae contenido limpio.

        Args:
            url: URL a crawlear
            extract_schema: Schema CSS para extracción estructurada
            use_llm_extraction: Si usar LLM para extracción inteligente

        Returns:
            CrawlResult con markdown, texto y metadata
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
                logger.warning("[Crawl4AI] Crawl fallido para %s: %s", url, result.error_message)
                return await self._httpx_fallback(url)

        except Exception as exc:
            logger.error("[Crawl4AI] Error en crawl de %s: %s", url, exc)
            return await self._httpx_fallback(url)

    async def crawl_competitor(
        self,
        competitor_url: str,
        extract_pricing: bool = True,
        extract_features: bool = True,
    ) -> dict[str, Any]:
        """
        Analiza un sitio de competidor extrayendo información clave.

        Args:
            competitor_url: URL del competidor
            extract_pricing: Si extraer información de precios
            extract_features: Si extraer características del producto

        Returns:
            Análisis estructurado del competidor
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
            # Extraer información clave del contenido
            content_lower = result.markdown.lower()

            # Detectar precios
            if extract_pricing:
                import re

                prices = re.findall(
                    r"\$[\d,]+(?:\.\d{2})?(?:/(?:mo|month|yr|year|mes|año))?", result.markdown
                )
                analysis["detected_prices"] = prices[:10]

            # Detectar características
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

            # Detectar tecnologías
            tech_keywords = ["react", "vue", "angular", "shopify", "wordpress", "stripe", "paypal"]
            analysis["detected_tech"] = [tech for tech in tech_keywords if tech in content_lower]

        return analysis

    async def batch_crawl(
        self,
        urls: list[str],
        max_concurrent: int = 5,
    ) -> list[CrawlResult]:
        """
        Crawlea múltiples URLs en paralelo.

        Args:
            urls: Lista de URLs a crawlear
            max_concurrent: Máximo de crawls simultáneos

        Returns:
            Lista de CrawlResults
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
        """Fallback usando httpx cuando Crawl4AI no está disponible."""
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
                # Eliminar scripts y estilos
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


# ── Motor de Conversión con Firecrawl ────────────────────────────────────────


class FirecrawlEngine:
    """
    Motor de conversión web a datos con Firecrawl.

    Ideal para:
    - Convertir webs completas a datos estructurados
    - Mapear sitios para auditorías SEO
    - Analizar negocios automáticamente
    - Extraer datos de sitios con autenticación
    """

    def __init__(self, api_key: str = "") -> None:
        self._api_key = api_key
        self._app: Any = None

        if FIRECRAWL_AVAILABLE and api_key:
            try:
                self._app = FirecrawlApp(api_key=api_key)
                logger.info("[Firecrawl] App inicializada correctamente")
            except Exception as exc:
                logger.warning("[Firecrawl] Error inicializando: %s", exc)

    def _is_available(self) -> bool:
        return self._app is not None

    async def scrape_url(
        self,
        url: str,
        formats: list[str] | None = None,
    ) -> CrawlResult:
        """
        Convierte una URL a datos limpios con Firecrawl.

        Args:
            url: URL a scrapear
            formats: Formatos de salida ['markdown', 'html', 'links', 'screenshot']

        Returns:
            CrawlResult con el contenido estructurado
        """
        if not self._is_available():
            logger.info("[Firecrawl] No disponible, usando Crawl4AI como fallback")
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
            logger.warning("[Firecrawl] Scrape fallido para %s", url)
            crawl4ai = Crawl4AIEngine()
            return await crawl4ai.crawl_url(url)

        except Exception as exc:
            logger.error("[Firecrawl] Error en scrape de %s: %s", url, exc)
            crawl4ai = Crawl4AIEngine()
            return await crawl4ai.crawl_url(url)

    async def map_site(
        self,
        url: str,
        limit: int = 50,
    ) -> dict[str, Any]:
        """
        Mapea todas las URLs de un sitio web.
        Útil para auditorías SEO y análisis de estructura de competidores.

        Args:
            url: URL raíz del sitio
            limit: Máximo de URLs a mapear

        Returns:
            Mapa del sitio con URLs y metadata
        """
        if not self._is_available():
            # Fallback: crawlear la página principal y extraer links
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
            logger.error("[Firecrawl] Error mapeando %s: %s", url, exc)
            return {"url": url, "links": [], "error": str(exc), "source": "firecrawl"}

    async def crawl_site(
        self,
        url: str,
        limit: int = 10,
        include_paths: list[str] | None = None,
    ) -> list[CrawlResult]:
        """
        Crawlea un sitio completo con Firecrawl.

        Args:
            url: URL raíz
            limit: Máximo de páginas
            include_paths: Paths específicos a incluir (ej: ['/pricing', '/features'])

        Returns:
            Lista de CrawlResults para cada página
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
            logger.error("[Firecrawl] Error crawleando sitio %s: %s", url, exc)
            return []

    async def analyze_business(
        self,
        business_url: str,
    ) -> dict[str, Any]:
        """
        Analiza un negocio automáticamente extrayendo información clave.
        Integra con el MarketingAgent y CFO Agent de Aria.

        Args:
            business_url: URL del negocio a analizar

        Returns:
            Análisis completo del negocio
        """
        # Scrape la página principal
        main_page = await self.scrape_url(business_url)

        # Intentar páginas clave
        f"{urlparse(business_url).scheme}://{urlparse(business_url).netloc}"

        analysis = {
            "url": business_url,
            "domain": urlparse(business_url).netloc,
            "main_content": main_page.markdown[:3000] if main_page.markdown else "",
            "success": main_page.success,
            "source": main_page.source,
        }

        # Mapear sitio para estructura
        site_map = await self.map_site(business_url, limit=20)
        analysis["site_structure"] = {
            "total_pages": site_map.get("total_pages", 0),
            "sample_urls": site_map.get("links", [])[:10],
        }

        return analysis


# ── Motor Unificado de Market Intelligence ───────────────────────────────────


class MarketIntelligenceEngine:
    """
    Motor unificado de Market Intelligence para ARIA AI.

    Combina Crawl4AI (scraping asíncrono) y Firecrawl (conversión web a datos)
    para proporcionar capacidades completas de análisis de mercado.

    Integra con:
    - web_tools.py (búsqueda web existente)
    - market_tools.py (análisis de mercado existente)
    - MarketingAgent (análisis de tendencias)
    - CFO Agent (análisis de competidores)
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
        Analiza múltiples competidores en paralelo.

        Args:
            competitor_urls: Lista de URLs de competidores
            niche: Nicho de mercado para contexto

        Returns:
            Análisis comparativo de competidores
        """
        logger.info("[MarketIntelligence] Analizando %d competidores", len(competitor_urls))

        # Crawlear todos en paralelo con Crawl4AI
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
        Extrae datos de mercado de una URL específica.

        Args:
            url: URL a analizar
            data_type: Tipo de datos ('pricing', 'features', 'reviews', 'general')

        Returns:
            Datos estructurados del mercado
        """
        # Usar Firecrawl si está disponible (mejor calidad), sino Crawl4AI
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
        Auditoría SEO básica de un sitio web.

        Args:
            url: URL del sitio a auditar

        Returns:
            Reporte SEO con estructura, links y metadata
        """
        # Mapear sitio con Firecrawl
        site_map = await self.firecrawl.map_site(url, limit=100)

        # Crawlear página principal para metadata
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
    """Retorna el singleton del motor de Market Intelligence."""
    global _engine_instance
    if _engine_instance is None:
        import os

        _engine_instance = MarketIntelligenceEngine(
            firecrawl_api_key=os.getenv("FIRECRAWL_API_KEY", ""),
        )
    return _engine_instance
