"""
research_agent.py — Agente de Investigación Avanzado para ARIA.

Combina las capacidades de Manus:
- Búsqueda web profunda
- Análisis de fuentes
- Extracción de datos
- Síntesis de información
- Citación automática
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

from apps.core.agents.base_agent import BaseAgent
from apps.core.tools.ai_client import AIModel, get_ai_client
from apps.core.tools.aria_tools import tool_registry

logger = logging.getLogger("aria.research_agent")


class ResearchAgent(BaseAgent):
    """Agente de investigación con capacidades avanzadas de búsqueda y análisis."""

    def __init__(self) -> None:
        super().__init__(
            name="research",
            description="Investigación profunda — búsqueda web, análisis, síntesis",
            capabilities=[
                "web_search",
                "data_extraction",
                "source_analysis",
                "information_synthesis",
                "citation_generation",
                "report_generation",
            ],
        )
        self.search_history: list[dict[str, Any]] = []
        self.sources: list[dict[str, Any]] = []

    async def _execute(self, context: dict[str, Any]) -> dict[str, Any]:
        """Punto de entrada principal."""
        query = context.get("query", "")
        context.get("research_type", "general")
        depth = context.get("depth", "medium")  # shallow, medium, deep
        max_sources = context.get("max_sources", 20)

        logger.info(f"[ResearchAgent] Iniciando investigación: {query[:80]}")

        try:
            # 1. Búsqueda web profunda
            sources = await self._deep_search(query, max_sources, depth)

            # 2. Análisis de fuentes
            analyzed_sources = await self._analyze_sources(sources)

            # 3. Síntesis de información
            synthesis = await self._synthesize_information(query, analyzed_sources)

            # 4. Generar reporte
            report = await self._generate_report(query, synthesis, analyzed_sources)

            return {
                "success": True,
                "query": query,
                "sources_count": len(analyzed_sources),
                "synthesis": synthesis,
                "report": report,
                "sources": analyzed_sources[:10],  # Top 10 sources
            }

        except Exception as exc:
            logger.error(f"[ResearchAgent] Error en investigación: {exc}")
            return {"success": False, "error": str(exc)}

    async def _deep_search(self, query: str, max_sources: int, depth: str) -> list[dict[str, Any]]:
        """Realiza una búsqueda web profunda."""
        logger.info(f"[ResearchAgent] Búsqueda profunda: {query}")

        sources = []

        try:
            # Búsqueda múltiple con diferentes estrategias
            search_queries = await self._generate_search_variants(query)

            for search_query in search_queries[:5]:
                # Buscar en múltiples motores
                google_results = await self._search_google(search_query)
                bing_results = await self._search_bing(search_query)
                duckduckgo_results = await self._search_duckduckgo(search_query)

                # Combinar y deduplicar
                all_results = google_results + bing_results + duckduckgo_results
                sources.extend(all_results)

            # Deduplicar por URL
            unique_sources = {}
            for source in sources:
                url = source.get("url", "")
                if url and url not in unique_sources:
                    unique_sources[url] = source

            sources = list(unique_sources.values())[:max_sources]

            # Extracción de contenido
            for source in sources:
                content = await self._extract_content(source.get("url", ""))
                source["content"] = content
                source["extracted_at"] = datetime.now(UTC).isoformat()

            self.sources = sources
            logger.info(f"[ResearchAgent] Encontradas {len(sources)} fuentes únicas")

            return sources

        except Exception as exc:
            logger.error(f"[ResearchAgent] Error en búsqueda: {exc}")
            return []

    async def _generate_search_variants(self, query: str) -> list[str]:
        """Genera variantes de la búsqueda para mayor cobertura."""
        ai = get_ai_client()
        if not ai:
            return [query]

        try:
            response = await ai.complete(
                system="Eres un experto en búsqueda. Genera 5 variantes de una búsqueda para máxima cobertura.",
                user=f"Genera variantes de búsqueda para: {query}",
                model=AIModel.FAST,
                max_tokens=300,
            )

            # Parsear respuesta
            variants = response.split("\n") if response else [query]
            return [v.strip() for v in variants if v.strip()][:5]

        except Exception as exc:
            logger.warning(f"[ResearchAgent] Error generando variantes: {exc}")
            return [query]

    async def _search_google(self, query: str) -> list[dict[str, Any]]:
        """Busca en Google."""
        # Implementación con Google Custom Search API
        # Por ahora, retornar lista vacía como placeholder
        logger.debug(f"[ResearchAgent] Buscando en Google: {query}")
        return []

    async def _search_bing(self, query: str) -> list[dict[str, Any]]:
        """Busca en Bing."""
        logger.debug(f"[ResearchAgent] Buscando en Bing: {query}")
        return []

    async def _search_duckduckgo(self, query: str) -> list[dict[str, Any]]:
        """Busca en DuckDuckGo."""
        logger.debug(f"[ResearchAgent] Buscando en DuckDuckGo: {query}")
        return []

    async def _extract_content(self, url: str) -> str:
        """Extrae contenido de una URL."""
        try:
            web_scraping_tool = tool_registry.get_tool("web_scraping")
            if not web_scraping_tool:
                return ""

            result = await web_scraping_tool.scrape_page(url)
            if result.get("success"):
                return json.dumps(result.get("data", {}))
            return ""

        except Exception as exc:
            logger.warning(f"[ResearchAgent] Error extrayendo contenido: {exc}")
            return ""

    async def _analyze_sources(self, sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Analiza la credibilidad y relevancia de las fuentes."""
        ai = get_ai_client()
        if not ai:
            return sources

        analyzed = []

        for source in sources:
            try:
                analysis_prompt = f"""Analiza esta fuente en términos de credibilidad y relevancia:

URL: {source.get('url', '')}
Título: {source.get('title', '')}
Contenido (primeros 500 chars): {source.get('content', '')[:500]}

Proporciona:
- Credibilidad (1-10)
- Relevancia (1-10)
- Tipo de fuente (académica, noticia, blog, etc.)
- Sesgo potencial (si aplica)"""

                response = await ai.complete(
                    system="Eres un analista de fuentes. Evalúa credibilidad y relevancia.",
                    user=analysis_prompt,
                    model=AIModel.FAST,
                    max_tokens=200,
                )

                source["analysis"] = response
                analyzed.append(source)

            except Exception as exc:
                logger.warning(f"[ResearchAgent] Error analizando fuente: {exc}")
                analyzed.append(source)

        return analyzed

    async def _synthesize_information(self, query: str, sources: list[dict[str, Any]]) -> str:
        """Sintetiza la información de múltiples fuentes."""
        ai = get_ai_client()
        if not ai:
            return "Síntesis no disponible"

        try:
            # Preparar resumen de fuentes
            sources_summary = "\n".join(
                [
                    f"- {s.get('title', 'Sin título')}: {s.get('content', '')[:300]}"
                    for s in sources[:10]
                ]
            )

            synthesis_prompt = f"""Sintetiza la información de estas fuentes sobre: {query}

FUENTES:
{sources_summary}

Proporciona:
1. Resumen ejecutivo (2-3 párrafos)
2. Puntos clave
3. Áreas de consenso
4. Áreas de desacuerdo
5. Conclusiones"""

            response = await ai.complete(
                system="Eres un sintetizador de información. Crea resúmenes coherentes y bien estructurados.",
                user=synthesis_prompt,
                model=AIModel.STRATEGY,
                max_tokens=1500,
            )

            return response

        except Exception as exc:
            logger.error(f"[ResearchAgent] Error sintetizando: {exc}")
            return "Error en síntesis"

    async def _generate_report(
        self,
        query: str,
        synthesis: str,
        sources: list[dict[str, Any]],
    ) -> str:
        """Genera un reporte formateado con citas."""
        ai = get_ai_client()
        if not ai:
            return synthesis

        try:
            citations = self._generate_citations(sources)

            report_prompt = f"""Genera un reporte profesional sobre: {query}

SÍNTESIS:
{synthesis}

CITAS DISPONIBLES:
{citations}

Formato del reporte:
- Introducción
- Hallazgos principales
- Análisis detallado
- Conclusiones
- Referencias"""

            response = await ai.complete(
                system="Eres un escritor técnico. Genera reportes profesionales bien estructurados.",
                user=report_prompt,
                model=AIModel.STRATEGY,
                max_tokens=2000,
            )

            return response

        except Exception as exc:
            logger.error(f"[ResearchAgent] Error generando reporte: {exc}")
            return synthesis

    def _generate_citations(self, sources: list[dict[str, Any]]) -> str:
        """Genera citas en formato APA."""
        citations = []

        for i, source in enumerate(sources[:20], 1):
            url = source.get("url", "")
            title = source.get("title", "Sin título")
            date = source.get("date", datetime.now().strftime("%Y-%m-%d"))

            # Formato APA simplificado
            citation = f"[{i}] {title}. Retrieved from {url} ({date})"
            citations.append(citation)

        return "\n".join(citations)
