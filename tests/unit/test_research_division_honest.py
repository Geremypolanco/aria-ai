"""Honesty tests — AriaResearchDivision never fabricates findings.

The research backend may be unavailable or misbehave. In every failure mode
the division must return status "unavailable" (or an empty report) with an
explicit error — never hardcoded "Emerging trend in X" findings.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest


def _division():
    from apps.core.intelligence.autonomous_research_division import AriaResearchDivision
    return AriaResearchDivision()


@pytest.mark.asyncio
async def test_backend_unavailable_returns_unavailable():
    division = _division()
    with patch(
        "apps.core.agents.research_agent.ResearchAgent",
        side_effect=ImportError("no research stack"),
    ):
        report = await division.generate_proactive_report("logistics")
    assert report["status"] == "unavailable"
    assert report["findings"] == []
    assert "error" in report


@pytest.mark.asyncio
async def test_failed_research_returns_unavailable_not_fake_findings():
    division = _division()
    fake_agent = AsyncMock()
    fake_agent.run = AsyncMock(return_value={"success": False, "error": "LLM timeout"})
    with patch(
        "apps.core.agents.research_agent.ResearchAgent", return_value=fake_agent
    ):
        report = await division.generate_proactive_report("logistics")
    assert report["status"] == "unavailable"
    assert report["findings"] == []
    assert "LLM timeout" in report["error"]


@pytest.mark.asyncio
async def test_malformed_report_dict_does_not_crash():
    # A misbehaving backend returning a string instead of a dict must not
    # raise AttributeError — it degrades to an empty report.
    division = _division()
    fake_agent = AsyncMock()
    fake_agent.run = AsyncMock(
        return_value={"success": True, "report": "just a string", "sources": "nope"}
    )
    with patch(
        "apps.core.agents.research_agent.ResearchAgent", return_value=fake_agent
    ):
        report = await division.generate_proactive_report("logistics")
    assert report["status"] == "completed"
    assert report["findings"] == []


@pytest.mark.asyncio
async def test_no_hardcoded_findings():
    division = _division()
    fake_agent = AsyncMock()
    fake_agent.run = AsyncMock(
        return_value={
            "success": True,
            "report": {"title": "Real", "findings": ["finding A"]},
            "sources": ["https://example.com"],
        }
    )
    with patch(
        "apps.core.agents.research_agent.ResearchAgent", return_value=fake_agent
    ):
        report = await division.generate_proactive_report("logistics")
    assert report["findings"] == ["finding A"]
    assert not any("Emerging trend in" in str(f) for f in report["findings"])
