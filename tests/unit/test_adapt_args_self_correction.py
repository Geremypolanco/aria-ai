"""Regression/feature test: _execute_with_retry()'s self-correction on a
failed tool call used to only exist for 2 of ARIA's ~100 tools
(generate_image's model swap, web_search's query-shortening) — every other
tool just retried with the exact same arguments that had already failed,
with zero chance of a different outcome. _adapt_args() now falls through to
a generic, LLM-based correction for every other tool: propose new argument
VALUES for the same keys, given the error, instead of blindly repeating
what just failed. Fails open (returns the original args unchanged) on any
LLM failure or a response that doesn't match the original argument keys —
a broken self-correction attempt must never break the retry loop itself.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from apps.core.cognition.aria_mind import AriaMind
from apps.core.tools.ai_client import AIModel

pytestmark = pytest.mark.asyncio


async def test_adapt_args_generate_image_still_swaps_model_on_attempt_1():
    """Preserved hand-tuned special case — must not regress."""
    mind = AriaMind()
    args = await mind._adapt_args("generate_image", {"prompt": "a cat"}, "error", attempt=1)
    assert args["_fallback_model"] == "stabilityai/stable-diffusion-xl-base-1.0"


async def test_adapt_args_generate_image_still_swaps_model_on_attempt_2():
    mind = AriaMind()
    args = await mind._adapt_args("generate_image", {"prompt": "a cat"}, "error", attempt=2)
    assert args["_fallback_model"] == "stabilityai/sdxl-turbo"


async def test_adapt_args_web_search_still_shortens_query():
    mind = AriaMind()
    long_query = "one two three four five six seven"
    args = await mind._adapt_args("web_search", {"query": long_query}, "error", attempt=1)
    assert args["query"] == "one two three four"


async def test_adapt_args_generic_calls_llm_and_returns_corrected_args():
    mind = AriaMind()
    fake_ai = AsyncMock()
    fake_ai.complete_json = AsyncMock(
        return_value={"tool_args": {"product_name": "Widget Pro", "category": "gadgets"}}
    )

    with patch.object(mind, "_ai_client", return_value=fake_ai):
        result = await mind._adapt_args(
            "optimize_product_seo",
            {"product_name": "widget", "category": ""},
            "category cannot be empty",
            attempt=0,
        )

    assert result == {"product_name": "Widget Pro", "category": "gadgets"}
    fake_ai.complete_json.assert_awaited_once()
    assert fake_ai.complete_json.call_args.kwargs["model"] == AIModel.FAST


async def test_adapt_args_generic_falls_back_when_llm_changes_the_key_set():
    """Guardrail: a response with different keys must never reach
    _execute_tool — that could smuggle in an unrelated argument shape."""
    mind = AriaMind()
    fake_ai = AsyncMock()
    fake_ai.complete_json = AsyncMock(return_value={"tool_args": {"totally_different_key": 1}})

    original = {"product_name": "widget", "category": ""}
    with patch.object(mind, "_ai_client", return_value=fake_ai):
        result = await mind._adapt_args("optimize_product_seo", original, "some error", attempt=0)

    assert result == original


async def test_adapt_args_generic_falls_back_when_llm_response_is_not_a_dict():
    mind = AriaMind()
    fake_ai = AsyncMock()
    fake_ai.complete_json = AsyncMock(return_value={"tool_args": "not a dict"})

    original = {"product_name": "widget"}
    with patch.object(mind, "_ai_client", return_value=fake_ai):
        result = await mind._adapt_args("optimize_product_seo", original, "error", attempt=0)

    assert result == original


async def test_adapt_args_generic_falls_back_when_no_ai_client():
    mind = AriaMind()
    original = {"product_name": "widget"}
    with patch.object(mind, "_ai_client", return_value=None):
        result = await mind._adapt_args("optimize_product_seo", original, "error", attempt=0)

    assert result == original


async def test_adapt_args_generic_falls_back_when_complete_json_raises():
    mind = AriaMind()
    fake_ai = AsyncMock()
    fake_ai.complete_json = AsyncMock(side_effect=RuntimeError("provider down"))

    original = {"product_name": "widget"}
    with patch.object(mind, "_ai_client", return_value=fake_ai):
        result = await mind._adapt_args("optimize_product_seo", original, "error", attempt=0)

    assert result == original


async def test_adapt_args_generic_skips_llm_call_for_empty_args():
    mind = AriaMind()
    fake_ai = AsyncMock()
    fake_ai.complete_json = AsyncMock(side_effect=AssertionError("must not be called"))

    with patch.object(mind, "_ai_client", return_value=fake_ai):
        result = await mind._adapt_args("get_status", {}, "error", attempt=0)

    assert result == {}
    fake_ai.complete_json.assert_not_awaited()


async def test_execute_with_retry_applies_generic_adaptation_between_attempts():
    """End-to-end: a tool without a hand-tuned adaptation still gets
    corrected args on its second attempt, sourced from the generic
    LLM-based correction — not a blind repeat of the failing args."""
    mind = AriaMind()
    fake_ai = AsyncMock()
    fake_ai.complete_json = AsyncMock(
        return_value={"tool_args": {"product_name": "Widget Pro", "category": "gadgets"}}
    )

    calls = []

    async def fake_execute_tool(tool, args, attempt=0, email=""):
        calls.append(dict(args))
        if attempt == 0:
            return "Error: category cannot be empty", {}
        return "SEO optimized successfully", {}

    with (
        patch.object(mind, "_ai_client", return_value=fake_ai),
        patch.object(mind, "_execute_tool", fake_execute_tool),
        patch("apps.core.cognition.aria_mind.asyncio.sleep", AsyncMock()),
    ):
        obs, media, executed_args = await mind._execute_with_retry(
            "optimize_product_seo", {"product_name": "widget", "category": ""}
        )

    assert "SEO optimized successfully" in obs
    assert len(calls) == 2
    assert calls[0] == {"product_name": "widget", "category": ""}
    assert calls[1] == {"product_name": "Widget Pro", "category": "gadgets"}
    # Regression (CodeRabbit, PR #131): the returned args must be whichever
    # ones actually produced the result — the adapted retry args, not the
    # caller's original pre-retry args — so a caller auditing/tracing this
    # call doesn't misattribute the result to arguments that were never run.
    assert executed_args == {"product_name": "Widget Pro", "category": "gadgets"}
