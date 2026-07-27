"""Regression/feature test: _execute_with_retry()'s self-correction loop
(_adapt_args, PR #130) can propose materially different argument VALUES for
a consequential tool on a failed attempt — not just a formatting fix, but a
different niche, a different cashflow amount, different PR content — yet
guardrails.review_tool_call() (Layer 2) was only ever invoked once, by the
caller, against the planner's ORIGINAL args, before _execute_with_retry ran
at all. Several CONSTITUTIONAL_REVIEW_TOOLS entries (record_cashflow_entry,
create_flash_sale, run_income, etc.) have no separate Layer-3 content/code
firewall either, so an LLM-adapted retry could execute for real with zero
safety review of what actually ran.

_execute_with_retry now re-runs review_tool_call() against the adapted args
whenever they differ from what was just reviewed AND the tool is in
CONSTITUTIONAL_REVIEW_TOOLS — declining (queuing for owner approval) rather
than executing the unreviewed adaptation.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from apps.core.cognition.aria_mind import AriaMind
from apps.core.safety.guardrails import PlanVerdict


@pytest.mark.asyncio
async def test_adapted_args_for_reviewed_tool_get_re_reviewed_and_declined():
    """End-to-end: attempt 0 fails, _adapt_args proposes new values for a
    CONSTITUTIONAL_REVIEW_TOOLS tool, and an unsafe re-review verdict must
    stop the retry loop instead of executing the adapted args."""
    mind = AriaMind()
    fake_ai = AsyncMock()
    fake_ai.complete_json = AsyncMock(
        return_value={"tool_args": {"niche_key": "a_totally_different_niche"}}
    )

    calls = []

    async def fake_execute_tool(tool, args, attempt=0, email=""):
        calls.append(dict(args))
        return "Error: niche not found", {}

    unsafe = PlanVerdict(safe=False, risk_score=0.9, reason="adapted niche looks non-compliant")
    fake_queue = AsyncMock()
    from apps.core.safety.hitl_queue import HitlRequest

    fake_queue.enqueue = AsyncMock(
        return_value=HitlRequest(
            request_id="req_retry1",
            chat_id="chat-1",
            email="owner@example.com",
            user_text="launch a niche",
            tool="launch_niche",
            tool_args={"niche_key": "a_totally_different_niche"},
            risk_score=0.9,
            risk_reason=unsafe.reason,
        )
    )

    with (
        patch.object(mind, "_ai_client", return_value=fake_ai),
        patch.object(mind, "_execute_tool", fake_execute_tool),
        patch("apps.core.cognition.aria_mind.asyncio.sleep", AsyncMock()),
        patch("apps.core.safety.guardrails.evaluate_plan", AsyncMock(return_value=unsafe)),
        patch("apps.core.safety.hitl_queue.get_hitl_queue", return_value=fake_queue),
    ):
        obs, media, executed_args = await mind._execute_with_retry(
            "launch_niche",
            {"niche_key": "original_niche"},
            email="someone@else.com",
            text="launch a niche",
            chat_id="chat-1",
        )

    # Only ONE execution attempt happened — the adapted args were reviewed
    # and declined BEFORE a second _execute_tool call, never executed.
    assert len(calls) == 1
    assert "req_retry1" in obs
    assert "owner" in obs.lower()
    assert executed_args == {"niche_key": "a_totally_different_niche"}


@pytest.mark.asyncio
async def test_adapted_args_for_reviewed_tool_proceed_when_review_is_safe():
    """A safe re-review verdict must let the adapted retry actually run."""
    mind = AriaMind()
    fake_ai = AsyncMock()
    fake_ai.complete_json = AsyncMock(
        return_value={"tool_args": {"niche_key": "a_different_but_fine_niche"}}
    )

    calls = []

    async def fake_execute_tool(tool, args, attempt=0, email=""):
        calls.append(dict(args))
        if attempt == 0:
            return "Error: niche not found", {}
        return "Niche launched successfully", {}

    safe = PlanVerdict(safe=True, risk_score=0.05, reason="benign")

    with (
        patch.object(mind, "_ai_client", return_value=fake_ai),
        patch.object(mind, "_execute_tool", fake_execute_tool),
        patch("apps.core.cognition.aria_mind.asyncio.sleep", AsyncMock()),
        patch("apps.core.safety.guardrails.evaluate_plan", AsyncMock(return_value=safe)),
    ):
        obs, media, executed_args = await mind._execute_with_retry(
            "launch_niche", {"niche_key": "original_niche"}
        )

    assert len(calls) == 2
    assert "successfully" in obs
    assert executed_args == {"niche_key": "a_different_but_fine_niche"}


@pytest.mark.asyncio
async def test_no_re_review_call_when_tool_not_constitutionally_reviewed():
    """Existing, non-reviewed tools (e.g. optimize_product_seo) must not pay
    the extra LLM-call latency/cost — no regression to the broad tool set."""
    mind = AriaMind()
    fake_ai = AsyncMock()
    fake_ai.complete_json = AsyncMock(
        return_value={"tool_args": {"product_name": "Widget Pro", "category": "gadgets"}}
    )

    async def fake_execute_tool(tool, args, attempt=0, email=""):
        if attempt == 0:
            return "Error: category cannot be empty", {}
        return "SEO optimized successfully", {}

    with (
        patch.object(mind, "_ai_client", return_value=fake_ai),
        patch.object(mind, "_execute_tool", fake_execute_tool),
        patch("apps.core.cognition.aria_mind.asyncio.sleep", AsyncMock()),
        patch(
            "apps.core.safety.guardrails.evaluate_plan",
            AsyncMock(side_effect=AssertionError("must not be called")),
        ),
    ):
        obs, media, executed_args = await mind._execute_with_retry(
            "optimize_product_seo", {"product_name": "widget", "category": ""}
        )

    assert "SEO optimized successfully" in obs
    assert executed_args == {"product_name": "Widget Pro", "category": "gadgets"}


@pytest.mark.asyncio
async def test_no_re_review_call_when_adapted_args_are_unchanged():
    """_adapt_args fails open to the original args on any adaptation error —
    re-reviewing identical args would just burn an extra LLM call for
    nothing, since Layer 2 already judged them once before this call."""
    mind = AriaMind()

    async def fake_execute_tool(tool, args, attempt=0, email=""):
        return "Error: something went wrong", {}

    with (
        patch.object(mind, "_ai_client", return_value=None),  # _adapt_args_generic no-ops
        patch.object(mind, "_execute_tool", fake_execute_tool),
        patch("apps.core.cognition.aria_mind.asyncio.sleep", AsyncMock()),
        patch(
            "apps.core.safety.guardrails.evaluate_plan",
            AsyncMock(side_effect=AssertionError("must not be called")),
        ),
    ):
        obs, media, executed_args = await mind._execute_with_retry(
            "launch_niche", {"niche_key": "original_niche"}, max_retries=2
        )

    assert executed_args == {"niche_key": "original_niche"}


def test_looks_like_pending_confirmation_matches_hitl_queue_decline():
    mind = AriaMind()
    decline = (
        "That needs my owner's approval before I can do it (safety review: risky). "
        "I've queued it for a decision — request `req_abc123`."
    )
    assert mind._looks_like_pending_confirmation(decline) is True


def test_looks_like_pending_confirmation_still_matches_confirm_token():
    mind = AriaMind()
    assert mind._looks_like_pending_confirmation("preview ready. confirm_token: xyz") is True


def test_looks_like_pending_confirmation_false_for_ordinary_observation():
    mind = AriaMind()
    assert mind._looks_like_pending_confirmation("Everything worked great!") is False
