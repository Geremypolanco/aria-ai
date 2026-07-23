"""Regression tests for two integrity/compliance bugs found auditing the
live 24/7 monetization path (Orchestrator.run_cycle() -> _auto_discover_agents()
loads CFOAgent and InvestorAgent directly; confirmed reachable, unlike several
other findings from the same audit pass that turned out to be dead code):

1. CFOAgent.publish_to_gumroad() recorded revenue (_register_revenue) the
   moment a Gumroad PRODUCT LISTING was created (HTTP 201) — before anyone
   had bought anything. Every published ebook fabricated phantom revenue in
   the metrics/Supabase revenue history.
2. InvestorAgent._execute() could auto-post real LinkedIn outreach
   (_execute_outreach) addressed to real firms (Sequoia Capital, Y
   Combinator, etc.) built from a hardcoded, unverified "example" investor
   list, whenever context["auto_outreach"] was True — with no human in the
   loop. Now gated behind request_human_approval(), which never
   auto-approves (see base_agent.py's own docstring on that method).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytestmark = pytest.mark.asyncio


async def test_publish_to_gumroad_does_not_register_revenue_on_listing_creation():
    from apps.core.agents.cfo_agent import CFOAgent

    agent = CFOAgent()
    agent._register_revenue = AsyncMock()

    fake_response = MagicMock()
    fake_response.status_code = 201
    fake_response.json.return_value = {
        "product": {"short_url": "https://gumroad.com/l/abc", "id": "prod_1"}
    }

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=fake_response)
        mock_client_cls.return_value.__aenter__.return_value = mock_client

        result = await agent.publish_to_gumroad(
            {"title": "AI Playbook", "description": "desc", "price_usd": 19.99}
        )

    assert result["success"] is True
    agent._register_revenue.assert_not_awaited()


async def test_investor_outreach_requires_human_approval_and_does_not_auto_fire():
    from apps.core.agents.business.investor_agent import InvestorAgent

    agent = InvestorAgent()
    agent.think = AsyncMock(return_value="Hola, somos ARIA AI...")
    agent.request_human_approval = AsyncMock(
        return_value={"success": True, "status": "pending", "approval_id": "abc123"}
    )
    agent._execute_outreach = AsyncMock(return_value={"sent_count": 99})

    result = await agent._execute({"mission": "find investors", "auto_outreach": True})

    agent.request_human_approval.assert_awaited_once()
    # The real LinkedIn-posting path must never fire without a completed approval.
    agent._execute_outreach.assert_not_awaited()
    assert result["outreach_results"]["status"] == "pending"


async def test_investor_outreach_not_attempted_when_auto_outreach_false():
    from apps.core.agents.business.investor_agent import InvestorAgent

    agent = InvestorAgent()
    agent.think = AsyncMock(return_value="Hola, somos ARIA AI...")
    agent.request_human_approval = AsyncMock()
    agent._execute_outreach = AsyncMock()

    result = await agent._execute({"mission": "find investors"})

    agent.request_human_approval.assert_not_awaited()
    agent._execute_outreach.assert_not_awaited()
    assert "outreach_results" not in result


async def test_research_investors_marks_results_as_unverified():
    from apps.core.agents.business.investor_agent import InvestorAgent

    agent = InvestorAgent()
    investors = await agent._research_investors("AI SaaS")

    assert investors
    assert all(inv.get("verified") is False for inv in investors)
