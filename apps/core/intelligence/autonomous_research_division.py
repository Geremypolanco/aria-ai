"""
autonomous_research_division.py — Autonomous Research Division for ARIA AI.

Agents that operate proactively (without human request):
  - Generate weekly market reports.
  - Perform deep competitive studies.
  - Detect new revenue opportunities.

ARIA doesn't wait for orders, Aria researches and proposes.
"""

from __future__ import annotations

import logging
from datetime import datetime

logger = logging.getLogger("aria.research_division")


class AriaResearchDivision:
    """
    ARIA's Autonomous Research Division.
    Manages the proactive production of business intelligence.
    """

    def __init__(self) -> None:
        pass

    async def generate_proactive_report(self, focus_area: str) -> dict:
        """Generates a proactive report about an area of interest.

        Delegates to the real ResearchAgent (web search + synthesis). If the
        research pipeline is unavailable or fails, the report is returned
        with status "unavailable" and an explicit error — never with
        fabricated findings.
        """
        logger.info("[ResearchDivision] Generating proactive report for: %s", focus_area)

        report_id = f"REP-{datetime.now().strftime('%Y%m%d-%H%M')}"

        try:
            from apps.core.agents.research_agent import ResearchAgent

            agent = ResearchAgent()
            result = await agent.run(
                {
                    "query": f"Emerging trends, opportunities and competitive landscape in {focus_area}",
                    "research_type": "market",
                    "depth": "medium",
                    "max_sources": 10,
                }
            )
        except Exception as exc:  # noqa: BLE001 — research stack unavailable
            logger.warning("[ResearchDivision] Research backend unavailable: %s", exc)
            return {
                "report_id": report_id,
                "title": f"Strategic Opportunities in {focus_area}",
                "status": "unavailable",
                "findings": [],
                "error": f"Research backend unavailable: {exc}",
            }

        if not result.get("success"):
            error = result.get("error", "unknown research failure")
            logger.warning("[ResearchDivision] Research failed: %s", error)
            return {
                "report_id": report_id,
                "title": f"Strategic Opportunities in {focus_area}",
                "status": "unavailable",
                "findings": [],
                "error": f"Research failed: {error}",
            }

        report = result.get("report") or {}
        return {
            "report_id": report_id,
            "title": report.get("title", f"Strategic Opportunities in {focus_area}"),
            "status": "completed",
            "findings": report.get("findings", []),
            "sources": result.get("sources", [])[:10],
            "generated_at": datetime.now().isoformat(),
        }


# ── Singleton ────────────────────────────────────────────────────────────────
_research_division_instance: AriaResearchDivision | None = None


def get_research_division() -> AriaResearchDivision:
    """Returns the research division singleton."""
    global _research_division_instance
    if _research_division_instance is None:
        _research_division_instance = AriaResearchDivision()
    return _research_division_instance
