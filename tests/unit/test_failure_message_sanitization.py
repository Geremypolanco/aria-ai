"""Regression test: when a tool call failed, ARIA used to hand the raw
observation straight to the user in three places — the '_synthesize' no-AI
fallback, its LLM-rephrase path, and the image-generation fast path's
caption — so a failed tool could leak an exception message, a provider error
payload, or an internal tool name verbatim. All three must now fall back to a
generic "something went wrong, I'll try again" message instead. Failures are
never handed to the LLM at all (see test below) since a model can still
quote/paraphrase raw error text despite being told not to."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from apps.core.cognition.aria_mind import AriaMind
from apps.core.tools.ai_client import AIProvider, AIResponse

pytestmark = pytest.mark.asyncio

RAW_ERROR = "Error: connection to internal-provider-7.svc timed out (code=ETIMEDOUT)"


async def test_synthesize_hides_raw_error_when_no_ai_client():
    mind = AriaMind()
    with patch.object(mind, "_ai_client", return_value=None):
        result = await mind._synthesize("do the thing", "some_tool", RAW_ERROR)

    assert RAW_ERROR not in result
    assert "went wrong" in result.lower()


async def test_synthesize_never_invokes_llm_for_a_failure_observation():
    """A failure short-circuits to the generic reply before ai.complete() is
    ever called — even a "successful" LLM response can't be trusted to have
    scrubbed the raw error out of what it was given, so the model must never
    see it in the first place."""
    mind = AriaMind()
    fake_ai = AsyncMock()
    fake_ai.complete = AsyncMock(
        return_value=AIResponse(
            content=f"Here's what happened: {RAW_ERROR}",
            provider=AIProvider.ANTHROPIC,
            model="strategy",
            success=True,
        )
    )
    with patch.object(mind, "_ai_client", return_value=fake_ai):
        result = await mind._synthesize("do the thing", "some_tool", RAW_ERROR)

    fake_ai.complete.assert_not_awaited()
    assert RAW_ERROR not in result
    assert "went wrong" in result.lower()


async def test_synthesize_still_passes_through_non_failure_observation_when_no_ai():
    mind = AriaMind()
    obs = "Here is a perfectly good result from the tool, no problems at all."
    with patch.object(mind, "_ai_client", return_value=None):
        result = await mind._synthesize("do the thing", "some_tool", obs)

    assert result == obs[:400]


async def test_image_fast_path_caption_hides_raw_error_on_failure():
    mind = AriaMind()

    async def fake_retry(tool, args, email=""):
        return RAW_ERROR, {}, args

    with (
        patch.object(mind, "_ai_client", return_value=AsyncMock()),
        patch.object(mind, "_execute_with_retry", fake_retry),
        patch.object(mind, "_record_exec", AsyncMock()),
        patch.object(mind, "_store_interaction", AsyncMock()),
        patch.object(mind, "_trace_turn", AsyncMock()),
    ):
        resp = await mind.handle("Create an image of a cat", "chat-1")

    assert RAW_ERROR not in resp.caption
    assert "went wrong" in resp.caption.lower()


async def test_synthesize_does_not_hide_deliberate_permission_denial():
    """A permission denial (e.g. owner-only tool gate) is a deliberate, clean,
    human-authored response, not a raw error — retrying can never change it,
    so it must reach the user as-is rather than a vague "something went
    wrong" that implies a transient, retryable failure."""
    mind = AriaMind()
    denial = "This action is reserved for ARIA's owner."
    with patch.object(mind, "_ai_client", return_value=None):
        result = await mind._synthesize("do the thing", "github_self", denial)

    assert result == denial[:400]
