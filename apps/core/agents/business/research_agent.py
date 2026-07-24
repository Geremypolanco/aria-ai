"""
Research Agent — In-depth research on market, competitors, and trends.

Combines web search, news analysis, HuggingFace models, and AI synthesis
to produce actionable intelligence reports.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from apps.core.agents.base_agent import BaseAgent

logger = logging.getLogger("aria.business.research")


class ResearchAgent(BaseAgent):
    IDENTITY = (
        "You are ARIA AI's Research Agent. You are an elite market analyst. "
        "You combine real internet data with deep analysis to produce actionable "
        "insights. You never make up data — you always cite real sources."
    )

    def __init__(self) -> None:
        super().__init__(
            name="research",
            description="In-depth research: market, competitors, trends, real internet data",
            capabilities=[
                "market_research",
                "competitor_analysis",
                "trend_analysis",
                "web_research",
                "data_synthesis",
                "report_generation",
            ],
        )

    async def _execute(self, context: dict[str, Any]) -> dict[str, Any]:
        mission = context.get("mission", "General market analysis")
        topic = context.get("topic", mission)
        depth = context.get("depth", "deep")  # quick | deep | comprehensive
        output_type = context.get("output", "report")  # report | bullets | pdf

        results: dict[str, Any] = {"success": True, "agent": "research", "topic": topic}

        if depth == "quick":
            # Quick search — 1 query
            raw = await self._quick_research(topic)
            results["data"] = raw
        elif depth == "deep":
            # Multiple angles in parallel
            research_data = await self._deep_research(topic)
            results["data"] = research_data
        else:
            # Comprehensive: deep + sentiment + trends
            research_data, trends, sentiment = await asyncio.gather(
                self._deep_research(topic),
                self._analyze_trends(topic),
                self._analyze_sentiment(topic),
                return_exceptions=True,
            )
            results["data"] = research_data if not isinstance(research_data, Exception) else {}
            results["trends"] = trends if not isinstance(trends, Exception) else {}
            results["sentiment"] = sentiment if not isinstance(sentiment, Exception) else {}

        # AI synthesis
        report = await self._synthesize_report(topic, results.get("data", {}), output_type)
        results["report"] = report

        # Generate PDF if requested
        if output_type == "pdf":
            from apps.core.tools.pdf_generator import generate_pdf

            pdf_result = await generate_pdf(
                title=f"Report: {topic[:50]}",
                content=report,
            )
            if pdf_result.get("success"):
                results["pdf_bytes"] = pdf_result["pdf_bytes"]
                results["pdf_filename"] = pdf_result["filename"]

        results["summary"] = report[:400] if report else "Research completed"
        return results

    async def _quick_research(self, topic: str) -> dict:
        from apps.core.tools.web_tools import WebTools

        return await WebTools().search_web(topic, num_results=5)

    async def _deep_research(self, topic: str) -> dict:
        """Deep search: multiple queries + fetching top pages."""
        from apps.core.tools.web_tools import WebTools

        wt = WebTools()

        queries = [
            topic,
            f"{topic} market size 2024 2025",
            f"{topic} competitors analysis",
            f"{topic} trends growth",
        ]

        search_tasks = [wt.search_web(q, num_results=5) for q in queries]
        search_results = await asyncio.gather(*search_tasks, return_exceptions=True)

        all_results: list[dict] = []
        urls_to_fetch: list[str] = []

        for r in search_results:
            if isinstance(r, dict) and r.get("success"):
                for item in r.get("results", [])[:3]:
                    all_results.append(item)
                    if item.get("url"):
                        urls_to_fetch.append(item["url"])

        # Fetch top 3 pages
        if urls_to_fetch:
            fetch_tasks = [wt.fetch_page(url, max_chars=2000) for url in urls_to_fetch[:3]]
            pages = await asyncio.gather(*fetch_tasks, return_exceptions=True)
            for url, page in zip(urls_to_fetch, pages, strict=False):
                if isinstance(page, dict) and page.get("success"):
                    all_results.append({"url": url, "content": page.get("text", "")[:1500]})

        return {"results": all_results, "queries": queries}

    async def _analyze_trends(self, topic: str) -> dict:
        from apps.core.tools.web_tools import WebTools

        wt = WebTools()
        hn, rd = await asyncio.gather(
            wt.get_hacker_news_trending(limit=10),
            wt.get_reddit_trending(limit=10),
            return_exceptions=True,
        )
        relevant_hn = []
        relevant_rd = []
        if isinstance(hn, dict) and hn.get("success"):
            relevant_hn = [
                s
                for s in hn.get("stories", [])
                if any(w in (s.get("title", "")).lower() for w in topic.lower().split())
            ][:5]
        if isinstance(rd, dict) and rd.get("success"):
            relevant_rd = [
                p
                for p in rd.get("posts", [])
                if any(w in (p.get("title", "")).lower() for w in topic.lower().split())
            ][:5]
        return {"hackernews": relevant_hn, "reddit": relevant_rd}

    async def _analyze_sentiment(self, topic: str) -> dict:
        try:
            from apps.core.tools.huggingface_suite import HuggingFaceSuite

            return await HuggingFaceSuite().analyze_sentiment(f"{topic} market trends growth")
        except Exception:
            return {}

    async def _synthesize_report(self, topic: str, data: dict, output_type: str) -> str:
        """Synthesizes all the data into an executive report with AI."""
        results_summary = str(data.get("results", []))[:3000]

        resp = await self.think(
            system=self.IDENTITY,
            user=(
                f"Topic: {topic}\n"
                f"Data collected: {results_summary}\n\n"
                f"Generate an executive report with:\n"
                f"## Executive Summary\n"
                f"## Market Size and Opportunity\n"
                f"## Key Players and Competitors\n"
                f"## Key Trends\n"
                f"## SWOT Analysis\n"
                f"## Strategic Recommendations\n"
                f"## Next Steps\n\n"
                f"Cite real sources when you have them. Be specific with numbers."
            ),
        )
        return resp
