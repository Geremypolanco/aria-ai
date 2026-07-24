"""Regression test: CEOAgent._identify_required_agents crashed with
TypeError when self.think() returned None (AI client unavailable/errored —
a documented, normal return path), since it did `(plan + mission).lower()`
with no None guard. run() catches the exception so it degraded to a generic
failure rather than crashing the request, but the agent could never
actually produce a plan whenever the AI was down — exactly when a fallback
should still work."""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, patch

from apps.core.agents.business.ceo_agent import CEOAgent


@pytest.mark.asyncio
async def test_execute_does_not_crash_when_think_returns_none():
    agent = CEOAgent()
    with patch.object(agent, "think", AsyncMock(return_value=None)):
        result = await agent.run({"mission": "grow revenue"})
    assert "object has no attribute" not in str(result.get("error", ""))
    assert "unsupported operand type" not in str(result.get("error", ""))


def test_identify_required_agents_handles_none_plan():
    agent = CEOAgent()
    # Previously raised TypeError: unsupported operand type(s) for +
    agents = agent._identify_required_agents(None, "launch a marketing campaign")
    assert "marketing" in agents
