"""Regression/feature test: a codebase survey (continuing pillar 3 — HITL
checkpoints before "major actions") found four tools with real, unrecallable
external side-effects that Layer 2 (constitutional review) never covered:

  - launch_niche / auto_income: create a real, immediately-purchasable
    Gumroad product (apps/core/tools/gumroad_tools.py's create_product with
    published="true") and publish public content (Medium/dev.to/Hashnode,
    a Zapier distribution webhook) — fully autonomously, with zero human
    review, unlike the Shopify revenue-suite tools (create_flash_sale etc.)
    which only ever produce draft copy.
  - send_email / publish_article: only ever had inline content-safety
    filtering (blocks unsafe *content*), nothing judging whether the action
    itself — sending a real email, publishing publicly — should happen.

All four are now in CONSTITUTIONAL_REVIEW_TOOLS, so they go through the same
review_tool_call() gate (LLM risk verdict → HITL approval queue on an unsafe
verdict) as execute_code/post_to_social/etc. — no new mechanism, just closing
the gap in the existing one.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from apps.core.safety.guardrails import CONSTITUTIONAL_REVIEW_TOOLS, PlanVerdict, review_tool_call

NEWLY_COVERED_TOOLS = ["launch_niche", "auto_income", "send_email", "publish_article"]


@pytest.mark.parametrize("tool", NEWLY_COVERED_TOOLS)
def test_tool_is_in_the_shared_review_set(tool):
    assert tool in CONSTITUTIONAL_REVIEW_TOOLS


@pytest.mark.asyncio
@pytest.mark.parametrize("tool", NEWLY_COVERED_TOOLS)
async def test_review_tool_call_actually_evaluates_it(tool):
    """The set membership alone proves nothing if review_tool_call() doesn't
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
async def test_launch_niche_gets_queued_for_owner_approval_when_risky():
    """End-to-end: an unsafe verdict on the highest-risk of the four (it
    autonomously creates and publishes a live, purchasable product) must
    queue for the owner rather than run immediately — the exact protection
    this tool previously had none of."""
    unsafe = PlanVerdict(
        safe=False, risk_score=0.8, reason="niche touches a regulated financial claim"
    )
    with (
        patch("apps.core.safety.guardrails.evaluate_plan", AsyncMock(return_value=unsafe)),
        patch("apps.core.safety.hitl_queue.get_hitl_queue") as mock_queue,
    ):
        fake_queue = AsyncMock()
        from apps.core.safety.hitl_queue import HitlRequest

        fake_queue.enqueue = AsyncMock(
            return_value=HitlRequest(
                request_id="req_niche1",
                chat_id="chat-1",
                email="owner@example.com",
                user_text="launch a niche about crypto trading signals",
                tool="launch_niche",
                tool_args={"niche_key": "crypto_signals"},
                risk_score=0.8,
                risk_reason=unsafe.reason,
            )
        )
        mock_queue.return_value = fake_queue

        decline = await review_tool_call(
            "launch_niche",
            {"niche_key": "crypto_signals"},
            "launch a niche about crypto trading signals",
            email="owner@example.com",
            chat_id="chat-1",
        )

    assert decline is not None
    assert "req_niche1" in decline
    assert "owner" in decline.lower()


@pytest.mark.asyncio
async def test_web_search_still_skipped_no_regression_to_the_broad_set():
    """Sanity check the fix didn't accidentally widen review to everything —
    only the tools with real side-effects should pay the extra LLM-call
    latency/cost."""
    with patch(
        "apps.core.safety.guardrails.evaluate_plan",
        AsyncMock(side_effect=AssertionError("must not be called for web_search")),
    ):
        decline = await review_tool_call("web_search", {"query": "yoga tips"}, "search")

    assert decline is None
