"""Regression test: a codebase survey (continuing the pattern from PR #134's
CONSTITUTIONAL_REVIEW_TOOLS audit) found two live-effect, money-moving tools
that were missing from BOTH safety gates their direct siblings already have:

  - run_income calls Orchestrator().run_cycle() — the exact same class of
    autonomous business cycle (real missions, real spend, real publishing)
    that auto_income/launch_niche run, both of which are owner-gated AND
    constitutionally reviewed.
  - square_sell creates a real Square catalog item + payment link via the
    owner's own SQUARE_ACCESS_TOKEN/SQUARE_LOCATION_ID — the same category
    of "owner's real credentials, real external side-effect" as
    create_flash_sale (Shopify), which is also gated both ways.

Neither name appeared in AriaMind._OWNER_ONLY_TOOLS nor in
guardrails.CONSTITUTIONAL_REVIEW_TOOLS, meaning any signed-up non-owner user
could trigger the owner's real autonomous income cycle, or create a real
Square product/payment link, through ordinary chat — with none of the
safety layers ever consulted. This was a gap by omission, not design.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from apps.core.cognition.aria_mind import AriaMind
from apps.core.safety.guardrails import CONSTITUTIONAL_REVIEW_TOOLS, PlanVerdict, review_tool_call

NEWLY_GATED_TOOLS = ["run_income", "square_sell"]


@pytest.mark.asyncio
@pytest.mark.parametrize("tool", NEWLY_GATED_TOOLS)
async def test_tool_blocked_for_non_owner(tool):
    mind = AriaMind()
    obs, media = await mind._execute_tool(tool, {}, email="someone@else.com")

    assert media == {}
    assert "owner" in obs.lower()


@pytest.mark.parametrize("tool", NEWLY_GATED_TOOLS)
def test_tool_is_in_the_owner_only_set(tool):
    assert tool in AriaMind._OWNER_ONLY_TOOLS


@pytest.mark.parametrize("tool", NEWLY_GATED_TOOLS)
def test_tool_is_in_the_constitutional_review_set(tool):
    assert tool in CONSTITUTIONAL_REVIEW_TOOLS


@pytest.mark.asyncio
@pytest.mark.parametrize("tool", NEWLY_GATED_TOOLS)
async def test_review_tool_call_actually_evaluates_it(tool):
    """Set membership alone proves nothing if review_tool_call() doesn't
    actually call evaluate_plan() for it — exercise the real gate function."""
    safe = PlanVerdict(safe=True, risk_score=0.05, reason="benign")
    with patch(
        "apps.core.safety.guardrails.evaluate_plan", AsyncMock(return_value=safe)
    ) as mock_eval:
        decline = await review_tool_call(tool, {"key": "value"}, "do the thing", email="u@x.com")

    mock_eval.assert_awaited_once()
    assert mock_eval.call_args.args[0] == tool
    assert decline is None


@pytest.mark.asyncio
async def test_square_sell_gets_queued_for_owner_approval_when_risky():
    """End-to-end: an unsafe verdict on square_sell must queue for the owner
    rather than run immediately — the exact protection this tool previously
    had none of."""
    unsafe = PlanVerdict(safe=False, risk_score=0.9, reason="price looks like a scam listing")
    with (
        patch("apps.core.safety.guardrails.evaluate_plan", AsyncMock(return_value=unsafe)),
        patch("apps.core.safety.hitl_queue.get_hitl_queue") as mock_queue,
    ):
        fake_queue = AsyncMock()
        from apps.core.safety.hitl_queue import HitlRequest

        fake_queue.enqueue = AsyncMock(
            return_value=HitlRequest(
                request_id="req_square1",
                chat_id="chat-1",
                email="owner@example.com",
                user_text="sell a product on square",
                tool="square_sell",
                tool_args={"name": "Suspicious Product", "price": 999999},
                risk_score=0.9,
                risk_reason=unsafe.reason,
            )
        )
        mock_queue.return_value = fake_queue

        decline = await review_tool_call(
            "square_sell",
            {"name": "Suspicious Product", "price": 999999},
            "sell a product on square",
            email="owner@example.com",
            chat_id="chat-1",
        )

    assert decline is not None
    assert "req_square1" in decline
    assert "owner" in decline.lower()
