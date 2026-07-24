"""Regression test: ComplianceAgent gates costed/high-impact actions (delete,
deploy, publish, send_bulk, purchase, or any amount_usd > 0) through
_ai_review(). When the AI reviewer was unavailable or errored, it used to
default to approved=True ("aprobado provisionalmente") — a compliance gate
that fails OPEN on its own malfunction defeats the entire point of gating
these actions. It must fail CLOSED: block the action and require human
review instead.

Found while building the SOC 2 / ISO 27001 / HIPAA technical gap-analysis —
ComplianceAgent is reachable live via telegram_bot.py -> aria_commands.py ->
AuditorAgent/execution_pipeline.py, not dead code.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from apps.core.agents.compliance_agent import ComplianceAgent

pytestmark = pytest.mark.asyncio


async def test_review_blocks_costed_action_when_ai_client_unavailable():
    agent = ComplianceAgent()
    with patch("apps.core.tools.ai_client.get_ai_client", return_value=None):
        result = await agent._execute(
            {"action_type": "purchase", "description": "buy ad credits", "amount_usd": 200.0}
        )

    assert result["approved"] is False
    assert result["needs_human_review"] is True
    assert result["risk_level"] == "HIGH"


async def test_review_blocks_high_impact_action_when_ai_call_raises():
    agent = ComplianceAgent()
    mock_ai = AsyncMock()
    mock_ai.complete = AsyncMock(side_effect=RuntimeError("provider down"))
    with patch("apps.core.tools.ai_client.get_ai_client", return_value=mock_ai):
        result = await agent._execute(
            {"action_type": "deploy", "description": "deploy new code", "amount_usd": 0}
        )

    assert result["approved"] is False
    assert result["needs_human_review"] is True


async def test_review_still_approves_when_ai_explicitly_approves():
    agent = ComplianceAgent()
    mock_response = AsyncMock()
    mock_response.success = True
    mock_response.content = '{"approved": true, "risk_level": "LOW", "reason": "fine"}'
    mock_ai = AsyncMock()
    mock_ai.complete = AsyncMock(return_value=mock_response)
    with patch("apps.core.tools.ai_client.get_ai_client", return_value=mock_ai):
        result = await agent._execute(
            {"action_type": "purchase", "description": "buy ad credits", "amount_usd": 200.0}
        )

    assert result["approved"] is True
    assert result["ai_reviewed"] is True
