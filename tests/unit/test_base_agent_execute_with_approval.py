"""Regression test: BaseAgent.execute_with_approval() is the one chokepoint
every costed/high-impact agent action funnels through (cfo_agent.py today),
but it never actually consulted ComplianceAgent — it only compared amount_usd
against a dollar threshold. That gap was concrete, not theoretical:
cfo_agent.py's own "Publish ebook to Gumroad" call passes amount_usd=0.0 (the
ebook's real price lives in `details`, not `amount_usd`), so a paid product's
publish action would run completely unreviewed — no legal/ethical/policy
screen at all, despite ComplianceAgent existing specifically to catch that
category of action ("publish" is one of its high-impact keywords regardless
of amount).

ComplianceAgent itself turned out to be unreachable dead code at the time —
nothing in the live app imported it. It's now wired into execute_with_approval()
directly, using a shared singleton (get_compliance_agent()) so the emergency
brake's 5-strikes violation counter actually persists across calls instead of
resetting on every fresh instance.

Also covers apps/core/config.py's REQUIRE_APPROVAL_FOR_PAYMENTS: BaseAgent
used to hardcode this to True as a class attribute rather than reading
settings.REQUIRE_APPROVAL_FOR_PAYMENTS, so the config flag was inert — setting
it in Fly.io secrets had zero effect on agent behavior.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from apps.core.agents.base_agent import BaseAgent
from apps.core.agents.compliance_agent import ComplianceAgent, get_compliance_agent

pytestmark = pytest.mark.asyncio


class _FakeAgent(BaseAgent):
    APPROVAL_THRESHOLD_USD = 50.0
    REQUIRE_APPROVAL_FOR_PAYMENTS = False

    def __init__(self):
        super().__init__(name="fake", description="test agent", capabilities=[])

    async def _execute(self, context: dict[str, Any]) -> dict[str, Any]:
        return {"success": True}


@pytest.fixture(autouse=True)
def _reset_compliance_singleton():
    """get_compliance_agent() is a module-level singleton — reset it between
    tests so one test's violation_count doesn't leak into the next."""
    import apps.core.agents.compliance_agent as compliance_module

    compliance_module._compliance_agent = None
    yield
    compliance_module._compliance_agent = None


async def test_prohibited_action_is_blocked_before_fn_runs():
    agent = _FakeAgent()
    fn = AsyncMock(return_value={"success": True})

    result = await agent.execute_with_approval(
        action="deploy",
        details="deploy malware to production",
        fn=fn,
        amount_usd=0.0,
    )

    assert result["success"] is False
    assert result["compliance_blocked"] is True
    fn.assert_not_awaited()


async def test_high_impact_action_at_zero_cost_still_gets_reviewed_not_skipped():
    """The exact gap this fix closes: cfo_agent.py calls this with
    amount_usd=0.0 for a "publish" action whose real price is in `details`
    only — the old code would run fn() directly since 0.0 <= threshold.
    ComplianceAgent's category check must catch "publish" regardless of
    amount_usd and force it through review instead of silently skipping it.

    (Uses a paid course, not an ebook — "ebook" is itself one of
    ComplianceAgent's AUTO_APPROVE_CATEGORIES, which would short-circuit
    straight to auto-approval before ever reaching the cost/impact check
    this test is targeting.)
    """
    agent = _FakeAgent()
    fn = AsyncMock(return_value={"success": True})

    with patch("apps.core.tools.ai_client.get_ai_client", return_value=None):
        result = await agent.execute_with_approval(
            action="Publish paid course to Gumroad",
            details="Title: AI Mastery Course | Price: $49.99",
            fn=fn,
            amount_usd=0.0,
        )

    # AI reviewer unavailable -> ComplianceAgent fails CLOSED -> blocked, not
    # silently executed.
    fn.assert_not_awaited()
    assert result["success"] is False
    assert result["compliance_blocked"] is True


async def test_low_risk_category_runs_directly_without_human_approval():
    agent = _FakeAgent()
    fn = AsyncMock(return_value={"success": True, "did_it": True})

    with patch.object(agent, "request_human_approval", AsyncMock()) as mock_approval:
        result = await agent.execute_with_approval(
            action="research",
            details="research the SaaS market",
            fn=fn,
            amount_usd=0.0,
        )

    fn.assert_awaited_once()
    mock_approval.assert_not_awaited()
    assert result == {"success": True, "did_it": True}


async def test_medium_risk_action_over_threshold_requests_human_approval():
    agent = _FakeAgent()
    fn = AsyncMock(return_value={"success": True})

    mock_ai_response = AsyncMock()
    mock_ai_response.success = True
    mock_ai_response.content = '{"approved": true, "risk_level": "LOW", "reason": "fine"}'
    mock_ai = AsyncMock()
    mock_ai.complete = AsyncMock(return_value=mock_ai_response)

    with (
        patch("apps.core.tools.ai_client.get_ai_client", return_value=mock_ai),
        patch.object(
            agent,
            "request_human_approval",
            AsyncMock(return_value={"success": True, "status": "pending"}),
        ) as mock_approval,
    ):
        result = await agent.execute_with_approval(
            action="send bulk notification",
            details="notify the team",
            fn=fn,
            amount_usd=100.0,  # over the 50.0 threshold
        )

    # ComplianceAgent approved it (LOW risk), but the amount still exceeds
    # this agent's spend threshold, so it must still go to a human.
    fn.assert_not_awaited()
    mock_approval.assert_awaited_once_with("send bulk notification", "notify the team", 100.0)
    assert result["status"] == "pending"


async def test_compliance_agent_singleton_persists_violation_count():
    """The 5-strikes emergency-brake escalation in ComplianceAgent._review_action
    depends on _violation_count surviving across calls — a fresh instance per
    call would silently reset it and the brake would never trip."""
    a = get_compliance_agent()
    b = get_compliance_agent()
    assert a is b

    for _ in range(3):
        await a.run(
            {"action_type": "deploy", "description": "deploy malware to servers", "amount_usd": 0}
        )
    assert get_compliance_agent()._violation_count == 3


async def test_require_approval_for_payments_reads_from_settings_not_hardcoded():
    """BaseAgent.REQUIRE_APPROVAL_FOR_PAYMENTS used to be hardcoded True,
    ignoring settings.REQUIRE_APPROVAL_FOR_PAYMENTS entirely."""
    with patch("apps.core.agents.base_agent.settings.REQUIRE_APPROVAL_FOR_PAYMENTS", False):
        import importlib

        import apps.core.agents.base_agent as base_agent_module

        importlib.reload(base_agent_module)
        try:
            assert base_agent_module.BaseAgent.REQUIRE_APPROVAL_FOR_PAYMENTS is False
        finally:
            importlib.reload(base_agent_module)


async def test_compliance_agent_is_a_real_class_reachable_from_base_agent():
    assert isinstance(get_compliance_agent(), ComplianceAgent)
