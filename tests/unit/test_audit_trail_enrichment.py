"""Regression/feature test: AITrace/_trace_turn() used to only capture the
user's message and the final, already-synthesized reply — a real gap for
debugging/audit, since there was no way to see the tool's actual call args
or what it actually returned before _synthesize() rewrote it into the final
reply. Both are now optional fields threaded through CognitionTracer.record()
and AriaMind._trace_turn(), bounded like every other free-text field here so
a large tool_args payload (e.g. execute_code's code) can't bloat storage.
"""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from apps.core.cognition.aria_mind import AriaMind
from apps.evaluation.phoenix.tracer import AITrace, CognitionTracer


def _mock_cache():
    c = MagicMock()
    c.get = AsyncMock(return_value=None)
    c.set = AsyncMock(return_value=True)
    return c


@pytest.fixture
def tracer():
    with patch("apps.evaluation.phoenix.tracer.get_cache", return_value=_mock_cache()):
        t = CognitionTracer()
        t._loaded = True
        return t


def test_ai_trace_to_dict_includes_tool_args_and_raw_observation():
    trace = AITrace(
        agent_name="aria_mind",
        task_type="web_search",
        prompt="find the news",
        response="Here's what I found: ...",
        tool_args={"query": "latest news"},
        raw_observation="1. Article A\n2. Article B",
    )
    d = trace.to_dict()
    assert d["tool_args"] == "{'query': 'latest news'}"
    assert d["raw_observation"] == "1. Article A\n2. Article B"


def test_ai_trace_to_dict_defaults_are_empty():
    trace = AITrace(agent_name="aria_mind", task_type="conversation")
    d = trace.to_dict()
    assert d["tool_args"] is None
    assert d["raw_observation"] == ""


def test_ai_trace_to_dict_bounds_a_large_tool_args_payload():
    huge_args = {"code": "x = 1\n" * 500}
    trace = AITrace(agent_name="aria_mind", task_type="execute_code", tool_args=huge_args)
    d = trace.to_dict()
    assert len(d["tool_args"]) <= 300


def test_ai_trace_to_dict_bounds_a_large_raw_observation():
    trace = AITrace(agent_name="aria_mind", task_type="deep_search", raw_observation="x" * 5000)
    d = trace.to_dict()
    assert len(d["raw_observation"]) <= 500


@pytest.mark.asyncio
async def test_tracer_record_passes_tool_args_and_raw_observation_through(tracer):
    with patch("apps.evaluation.phoenix.tracer.get_cache", return_value=_mock_cache()):
        trace = await tracer.record(
            agent_name="aria_mind",
            task_type="web_search",
            prompt="find the news",
            response="synthesized reply",
            tool_args={"query": "latest news"},
            raw_observation="1. Article A\n2. Article B",
        )

    assert trace.tool_args == {"query": "latest news"}
    assert trace.raw_observation == "1. Article A\n2. Article B"


@pytest.mark.asyncio
async def test_trace_turn_passes_tool_args_and_observation_to_the_tracer():
    mind = AriaMind()
    fake_tracer = AsyncMock()

    with patch("apps.evaluation.phoenix.tracer.get_cognition_tracer", return_value=fake_tracer):
        await mind._trace_turn(
            "web_search",
            "find the news",
            "synthesized reply",
            time.monotonic(),
            True,
            chat_id="chat-1",
            email="owner@example.com",
            tool_args={"query": "latest news"},
            raw_observation="1. Article A\n2. Article B",
        )

    fake_tracer.record.assert_awaited_once()
    kwargs = fake_tracer.record.call_args.kwargs
    assert kwargs["tool_args"] == {"query": "latest news"}
    assert kwargs["raw_observation"] == "1. Article A\n2. Article B"


@pytest.mark.asyncio
async def test_trace_turn_defaults_to_empty_for_conversation_turns():
    """The "conversation" task_type call site has neither — must not crash
    or send garbage when the caller omits them."""
    mind = AriaMind()
    fake_tracer = AsyncMock()

    with patch("apps.evaluation.phoenix.tracer.get_cognition_tracer", return_value=fake_tracer):
        await mind._trace_turn(
            "conversation", "hello", "hi there", time.monotonic(), True, chat_id="chat-1"
        )

    kwargs = fake_tracer.record.call_args.kwargs
    assert kwargs["tool_args"] is None
    assert kwargs["raw_observation"] == ""


@pytest.mark.asyncio
async def test_trace_turn_never_raises_when_tracer_itself_fails():
    """Matches this method's existing contract: a tracing failure must never
    affect the actual reply the user already received."""
    mind = AriaMind()
    with patch(
        "apps.evaluation.phoenix.tracer.get_cognition_tracer",
        side_effect=RuntimeError("tracer down"),
    ):
        await mind._trace_turn(
            "web_search",
            "find the news",
            "reply",
            time.monotonic(),
            True,
            tool_args={"query": "x"},
            raw_observation="obs",
        )
    # No exception raised — that's the assertion.
