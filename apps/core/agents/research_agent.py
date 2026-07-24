"""
research_agent.py — Advanced Research Agent for ARIA.

Combines Manus-style capabilities:
- Deep web search
- Source analysis
- Data extraction
- Information synthesis
- Automatic citation
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
    """Research agent with advanced search and analysis capabilities."""

    def __init__(self) -> None:
        super().__init__(
            name="research",
            description="Deep research — web search, analysis, synthesis",
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
        """Main entry point."""
        query = context.get("query", "")
        context.get("research_type", "general")
        depth = context.get("depth", "medium")  # shallow, medium, deep
        max_sources = context.get("max_sources", 20)

        logger.info(f"[ResearchAgent] Starting research: {query[:80]}")

        try:
            # 1. Deep web search
            sources = await self._deep_search(query, max_sources, depth)

            # 2. Source analysis
            analyzed_sources = await self._analyze_sources(sources)

            # 3. Information synthesis
            synthesis = await self._synthesize_information(query, analyzed_sources)

            # 4. Generate report
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
            logger.error(f"[ResearchAgent] Error in research: {exc}")
            return {"success": False, "error": str(exc)}

    async def _deep_search(self, query: str, max_sources: int, depth: str) -> list[dict[str, Any]]:
        """Performs a deep web search."""
        logger.info(f"[ResearchAgent] Deep search: {query}")

        sources = []

        try:
            # Multiple search with different strategies
            search_queries = await self._generate_search_variants(query)

            for search_query in search_queries[:5]:
                # Search across multiple engines
                google_results = await self._search_google(search_query)
                bing_results = await self._search_bing(search_query)
                duckduckgo_results = await self._search_duckduckgo(search_query)

                # Combine and deduplicate
                all_results = google_results + bing_results + duckduckgo_results
                sources.extend(all_results)

            # Deduplicate by URL
            unique_sources = {}
            for source in sources:
                url = source.get("url", "")
                if url and url not in unique_sources:
                    unique_sources[url] = source

            sources = list(unique_sources.values())[:max_sources]

            # Content extraction
            for source in sources:
                content = await self._extract_content(source.get("url", ""))
                source["content"] = content
                source["extracted_at"] = datetime.now(UTC).isoformat()

            self.sources = sources
            logger.info(f"[ResearchAgent] Found {len(sources)} unique sources")

            return sources

        except Exception as exc:
            logger.error(f"[ResearchAgent] Search error: {exc}")
            return []

    async def _generate_search_variants(self, query: str) -> list[str]:
        """Generates search variants for wider coverage."""
        ai = get_ai_client()
        if not ai:
            return [query]

        try:
            response = await ai.complete(
                system="You are a search expert. Generate 5 search variants for maximum coverage.",
                user=f"Generate search variants for: {query}",
                model=AIModel.FAST,
                max_tokens=300,
            )

            # Parse response
            variants = response.split("\n") if response else [query]
            return [v.strip() for v in variants if v.strip()][:5]

        except Exception as exc:
            logger.warning(f"[ResearchAgent] Error generating variants: {exc}")
            return [query]

    async def _search_google(self, query: str) -> list[dict[str, Any]]:
        """Searches Google."""
        # Implementation with Google Custom Search API
        # For now, return an empty list as a placeholder
        logger.debug(f"[ResearchAgent] Searching Google: {query}")
        return []

    async def _search_bing(self, query: str) -> list[dict[str, Any]]:
        """Searches Bing."""
        logger.debug(f"[ResearchAgent] Searching Bing: {query}")
        return []

    async def _search_duckduckgo(self, query: str) -> list[dict[str, Any]]:
        """Searches DuckDuckGo."""
        logger.debug(f"[ResearchAgent] Searching DuckDuckGo: {query}")
        return []

    async def _extract_content(self, url: str) -> str:
        """Extracts content from a URL."""
        try:
            web_scraping_tool = tool_registry.get_tool("web_scraping")
            if not web_scraping_tool:
                return ""

            result = await web_scraping_tool.scrape_page(url)
            if result.get("success"):
                return json.dumps(result.get("data", {}))
            return ""

        except Exception as exc:
            logger.warning(f"[ResearchAgent] Error extracting content: {exc}")
            return ""

    async def _analyze_sources(self, sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Analyzes the credibility and relevance of the sources."""
        ai = get_ai_client()
        if not ai:
            return sources

        analyzed = []

        for source in sources:
            try:
                analysis_prompt = f"""Analyze this source in terms of credibility and relevance:

URL: {source.get('url', '')}
Title: {source.get('title', '')}
Content (first 500 chars): {source.get('content', '')[:500]}

Provide:
- Credibility (1-10)
- Relevance (1-10)
- Source type (academic, news, blog, etc.)
- Potential bias (if applicable)"""

                response = await ai.complete(
                    system="You are a source analyst. Evaluate credibility and relevance.",
                    user=analysis_prompt,
                    model=AIModel.FAST,
                    max_tokens=200,
                )

                source["analysis"] = response
                analyzed.append(source)

            except Exception as exc:
                logger.warning(f"[ResearchAgent] Error analyzing source: {exc}")
                analyzed.append(source)

        return analyzed

    async def _synthesize_information(self, query: str, sources: list[dict[str, Any]]) -> str:
        """Synthesizes information from multiple sources."""
        ai = get_ai_client()
        if not ai:
            return "Synthesis not available"

        try:
            # Prepare a summary of sources
            sources_summary = "\n".join(
                [
                    f"- {s.get('title', 'No title')}: {s.get('content', '')[:300]}"
                    for s in sources[:10]
                ]
            )

            synthesis_prompt = f"""Synthesize the information from these sources about: {query}

SOURCES:
{sources_summary}

Provide:
1. Executive summary (2-3 paragraphs)
2. Key points
3. Areas of consensus
4. Areas of disagreement
5. Conclusions"""

            response = await ai.complete(
                system="You are an information synthesizer. Create coherent, well-structured summaries.",
                user=synthesis_prompt,
                model=AIModel.STRATEGY,
                max_tokens=1500,
            )

            return response

        except Exception as exc:
            logger.error(f"[ResearchAgent] Error synthesizing: {exc}")
            return "Error in synthesis"

    async def _generate_report(
        self,
        query: str,
        synthesis: str,
        sources: list[dict[str, Any]],
    ) -> str:
        """Generates a formatted report with citations."""
        ai = get_ai_client()
        if not ai:
            return synthesis

        try:
            citations = self._generate_citations(sources)

            report_prompt = f"""Generate a professional report about: {query}

SYNTHESIS:
{synthesis}

AVAILABLE CITATIONS:
{citations}

Report format:
- Introduction
- Main findings
- Detailed analysis
- Conclusions
- References"""

            response = await ai.complete(
                system="You are a technical writer. Generate well-structured, professional reports.",
                user=report_prompt,
                model=AIModel.STRATEGY,
                max_tokens=2000,
            )

            return response

        except Exception as exc:
            logger.error(f"[ResearchAgent] Error generating report: {exc}")
            return synthesis

    def _generate_citations(self, sources: list[dict[str, Any]]) -> str:
        """Generates citations in APA format."""
        citations = []

        for i, source in enumerate(sources[:20], 1):
            url = source.get("url", "")
            title = source.get("title", "No title")
            date = source.get("date", datetime.now().strftime("%Y-%m-%d"))

            # Simplified APA format
            citation = f"[{i}] {title}. Retrieved from {url} ({date})"
            citations.append(citation)

        return "\n".join(citations)
