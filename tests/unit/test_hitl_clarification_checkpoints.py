"""Feature test: pillar-3 HITL checkpoints. Previously, "ask before acting"
was pure prose in SYSTEM_TEMPLATE ("ask 1-3 short questions... and wait for
the answer") with nothing structurally enforcing the wait — the model's
clarifying question was indistinguishable from any other reply, and the
NEXT turn re-planned from scratch with only a short, out-of-context user
message, no memory that a question had even been asked.

This adds a real (not just prose) pause:
  - `_reason()`'s plan schema gains `needs_clarification`. When true (and no
    tool was picked), `handle()` stores the question + original request in
    per-chat state and returns immediately — no tool execution, no fake
    progress.
  - On the next turn, that stored context is folded into what the planner
    sees, so a short answer ("B2B analytics, mid-market") is interpreted
    against the original ask instead of as a fresh, contextless message.
  - `MindResponse.awaiting_input` surfaces every kind of pause (clarifying
    question, Layer 2's owner-approval queue, post_to_social's confirm-token
    preview) so callers can render a distinct "waiting for you" state
    instead of treating a pause like a completed turn.
"""

from __future__ import annotations

from contextlib import ExitStack
from unittest.mock import AsyncMock, patch

import pytest

from apps.core.cognition.aria_mind import SYSTEM_TEMPLATE, AriaMind, MindResponse


def _enter_common_stubs(stack: ExitStack, mind: AriaMind, fake_reason, load_state=None):
    stack.enter_context(patch("apps.core.config.settings.GUARDRAILS_ENABLED", False))
    stack.enter_context(patch.object(mind, "_reason", fake_reason))
    stack.enter_context(patch.object(mind, "_load_history", AsyncMock(return_value=[])))
    stack.enter_context(patch.object(mind, "_load_state", AsyncMock(return_value=load_state or {})))
    stack.enter_context(patch.object(mind, "_load_goals", AsyncMock(return_value=[])))
    stack.enter_context(patch.object(mind, "_load_learned", AsyncMock(return_value=[])))
    stack.enter_context(patch.object(mind, "_store_interaction", AsyncMock()))
    stack.enter_context(patch.object(mind, "_maybe_reflect", AsyncMock()))
    stack.enter_context(patch.object(mind, "_trace_turn", AsyncMock()))
    stack.enter_context(patch.object(mind, "_record_exec", AsyncMock()))


def test_mind_response_defaults_awaiting_input_to_false():
    assert MindResponse().awaiting_input is False


def test_reason_schema_instructs_needs_clarification_field():
    assert '"needs_clarification"' in SYSTEM_TEMPLATE
    assert '"tool" must be null' in SYSTEM_TEMPLATE


def test_looks_like_pending_confirmation_detects_confirm_token_marker():
    mind = AriaMind()
    assert mind._looks_like_pending_confirmation(
        "Preview — not yet posted to twitter:\nhi\n\n"
        "Ask me to post this exact text again to confirm — "
        "confirm_token: abc123 (expires in 10 minutes)."
    )
    assert not mind._looks_like_pending_confirmation("Posted to twitter. https://x.com/1")
    assert not mind._looks_like_pending_confirmation("")


@pytest.mark.asyncio
async def test_handle_pauses_for_clarification_when_planner_flags_it():
    question = "What's the product about, and who's it for?"

    async def fake_reason(*a, **k):
        return {"tool": None, "tool_args": {}, "reply": question, "needs_clarification": True}

    mind = AriaMind()
    saved_state = {}

    async def fake_evolve_state(chat_id, state, text, goals):
        saved_state.update(state)

    with ExitStack() as stack:
        _enter_common_stubs(stack, mind, fake_reason)
        stack.enter_context(patch.object(mind, "_evolve_state", fake_evolve_state))

        resp = await mind.handle("give me 3 pricing tiers for my SaaS", "chat-1")

    assert resp.text == question
    assert resp.awaiting_input is True
    assert saved_state["awaiting_clarification"]["question"] == question
    assert (
        saved_state["awaiting_clarification"]["original_text"]
        == "give me 3 pricing tiers for my SaaS"
    )


@pytest.mark.asyncio
async def test_handle_falls_back_to_a_generic_question_when_reply_is_empty():
    async def fake_reason(*a, **k):
        return {"tool": None, "tool_args": {}, "reply": "", "needs_clarification": True}

    mind = AriaMind()
    with ExitStack() as stack:
        _enter_common_stubs(stack, mind, fake_reason)
        stack.enter_context(patch.object(mind, "_evolve_state", AsyncMock()))

        resp = await mind.handle("do the thing", "chat-1")

    assert resp.awaiting_input is True
    assert resp.text  # never an empty pause with nothing to show the user


@pytest.mark.asyncio
async def test_handle_folds_prior_clarification_into_the_next_reason_call():
    prior_state = {
        "awaiting_clarification": {
            "question": "What's the product about, and who's it for?",
            "original_text": "give me 3 pricing tiers for my SaaS",
        }
    }
    captured = {}

    async def fake_reason(text, *a, **k):
        captured["text"] = text
        return {"tool": None, "tool_args": {}, "reply": "Here are 3 tiers..."}

    mind = AriaMind()
    with ExitStack() as stack:
        _enter_common_stubs(stack, mind, fake_reason, load_state=prior_state)
        stack.enter_context(patch.object(mind, "_evolve_state", AsyncMock()))

        resp = await mind.handle(
            "It's a B2B analytics tool for mid-market marketing teams", "chat-1"
        )

    assert "give me 3 pricing tiers for my SaaS" in captured["text"]
    assert "What's the product about, and who's it for?" in captured["text"]
    assert "It's a B2B analytics tool for mid-market marketing teams" in captured["text"]
    assert resp.awaiting_input is False
    assert resp.text == "Here are 3 tiers..."


@pytest.mark.asyncio
async def test_handle_clears_awaiting_clarification_once_resolved():
    """A resolved round must not leak into a later, unrelated turn."""
    prior_state = {
        "awaiting_clarification": {"question": "Which platform?", "original_text": "post this"}
    }

    async def fake_reason(*a, **k):
        return {"tool": None, "tool_args": {}, "reply": "Got it, done."}

    mind = AriaMind()
    saved_state = {"untouched": True}

    async def fake_evolve_state(chat_id, state, text, goals):
        saved_state.update(state)

    with ExitStack() as stack:
        _enter_common_stubs(stack, mind, fake_reason, load_state=prior_state)
        stack.enter_context(patch.object(mind, "_evolve_state", fake_evolve_state))

        await mind.handle("twitter", "chat-1")

    assert "awaiting_clarification" not in saved_state


@pytest.mark.asyncio
async def test_needs_clarification_ignored_when_plan_also_picked_a_tool():
    """A well-formed plan never mixes these, but if it did, executing the
    tool must win — needs_clarification only means "no tool ran this turn"
    when it's actually true that no tool ran."""

    async def fake_reason(*a, **k):
        return {
            "tool": "web_search",
            "tool_args": {"query": "yoga tips"},
            "reply": "",
            "needs_clarification": True,
        }

    mind = AriaMind()
    with ExitStack() as stack:
        _enter_common_stubs(stack, mind, fake_reason)
        stack.enter_context(patch.object(mind, "_evolve_state", AsyncMock()))
        stack.enter_context(
            patch.object(
                mind,
                "_execute_with_retry",
                AsyncMock(return_value=("some results", {}, {"query": "yoga tips"})),
            )
        )
        stack.enter_context(
            patch.object(mind, "_synthesize", AsyncMock(return_value="Here's what I found."))
        )

        resp = await mind.handle("search for yoga tips", "chat-1")

    assert resp.text == "Here's what I found."
    assert resp.awaiting_input is False


@pytest.mark.asyncio
async def test_handle_marks_post_to_social_preview_as_awaiting_input():
    preview_obs = (
        "Preview — not yet posted to twitter:\nhi\n\n"
        "Ask me to post this exact text again to confirm — "
        "confirm_token: abc123 (expires in 10 minutes)."
    )

    async def fake_reason(*a, **k):
        return {"tool": "post_to_social", "tool_args": {"platform": "twitter", "text": "hi"}}

    mind = AriaMind()
    with ExitStack() as stack:
        _enter_common_stubs(stack, mind, fake_reason)
        stack.enter_context(patch.object(mind, "_evolve_state", AsyncMock()))
        stack.enter_context(
            patch.object(
                mind,
                "_execute_with_retry",
                AsyncMock(return_value=(preview_obs, {}, {"platform": "twitter", "text": "hi"})),
            )
        )
        stack.enter_context(
            patch.object(mind, "_synthesize", AsyncMock(return_value="Here's the preview..."))
        )

        resp = await mind.handle("post hi to twitter", "chat-1", email="owner@example.com")

    assert resp.awaiting_input is True


@pytest.mark.asyncio
async def test_handle_does_not_mark_a_completed_tool_call_as_awaiting_input():
    async def fake_reason(*a, **k):
        return {"tool": "post_to_social", "tool_args": {"platform": "twitter", "text": "hi"}}

    mind = AriaMind()
    with ExitStack() as stack:
        _enter_common_stubs(stack, mind, fake_reason)
        stack.enter_context(patch.object(mind, "_evolve_state", AsyncMock()))
        stack.enter_context(
            patch.object(
                mind,
                "_execute_with_retry",
                AsyncMock(
                    return_value=(
                        "**Posted to twitter.** https://x.com/1",
                        {},
                        {"platform": "twitter", "text": "hi"},
                    )
                ),
            )
        )
        stack.enter_context(patch.object(mind, "_synthesize", AsyncMock(return_value="Posted it!")))

        resp = await mind.handle(
            "post hi to twitter, confirm_token abc123", "chat-1", email="owner@example.com"
        )

    assert resp.awaiting_input is False
