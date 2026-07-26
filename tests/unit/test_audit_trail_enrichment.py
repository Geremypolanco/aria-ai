"""Regression/feature test: AITrace/_trace_turn() used to only capture the
user's message and the final, already-synthesized reply — a real gap for
debugging/audit, since there was no way to see the tool's actual call args
or what it actually returned before _synthesize() rewrote it into the final
reply. Both are now optional fields threaded through CognitionTracer.record()
and AriaMind._trace_turn(), bounded like every other free-text field here so
a large tool_args payload (e.g. execute_code's code) can't bloat storage.
"""

from __future__ import annotations

import json
import time
from contextlib import ExitStack
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from apps.core.cognition.aria_mind import AriaMind
from apps.core.safety.guardrails import ModerationResult
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
async def test_trace_turn_redacts_sensitive_tool_args_before_tracing_and_broadcasting():
    """Regression (CodeRabbit, PR #131 follow-up): tool_args used to reach
    both the tracer and the admin_activity broadcast completely unredacted —
    a real secret passed as a tool argument would be persisted/broadcast
    verbatim. Both consumers must see the SAME sanitized dict."""
    mind = AriaMind()
    fake_tracer = AsyncMock()
    published = []

    async def fake_publish(channel, message, **kwargs):
        published.append(message)

    with (
        patch("apps.evaluation.phoenix.tracer.get_cognition_tracer", return_value=fake_tracer),
        patch("apps.core.scale.log_bus.publish", side_effect=fake_publish),
    ):
        await mind._trace_turn(
            "check_social_session",
            "check my session",
            "session active",
            time.monotonic(),
            True,
            chat_id="chat-1",
            email="owner@example.com",
            tool_args={"platform": "twitter", "api_key": "sk-real-secret"},
            raw_observation="session active",
        )

    kwargs = fake_tracer.record.call_args.kwargs
    assert kwargs["tool_args"] == {"platform": "twitter", "api_key": "[REDACTED]"}

    assert len(published) == 1
    payload = json.loads(published[0])
    assert "sk-real-secret" not in payload["tool_args"]
    assert "[REDACTED]" in payload["tool_args"]


@pytest.mark.asyncio
async def test_trace_turn_redacts_secrets_in_raw_observation_text():
    """raw_observation is free text (e.g. an API error message that echoed
    back a key), so it needs pattern-based redaction rather than tool_args'
    key-name matching — same guarantee: both the tracer and the broadcast
    must see the identical, already-sanitized text."""
    mind = AriaMind()
    fake_tracer = AsyncMock()
    published = []

    async def fake_publish(channel, message, **kwargs):
        published.append(message)

    with (
        patch("apps.evaluation.phoenix.tracer.get_cognition_tracer", return_value=fake_tracer),
        patch("apps.core.scale.log_bus.publish", side_effect=fake_publish),
    ):
        await mind._trace_turn(
            "web_search",
            "look up my api status",
            "here's your status",
            time.monotonic(),
            True,
            chat_id="chat-1",
            email="owner@example.com",
            tool_args={},
            raw_observation="Error: Authorization: Bearer sk-abcDEF123456789012345 rejected",
        )

    kwargs = fake_tracer.record.call_args.kwargs
    assert "sk-abcDEF123456789012345" not in kwargs["raw_observation"]
    assert "[REDACTED]" in kwargs["raw_observation"]

    payload = json.loads(published[0])
    assert "sk-abcDEF123456789012345" not in payload["raw_observation"]
    assert "[REDACTED]" in payload["raw_observation"]


@pytest.mark.asyncio
async def test_record_exec_also_redacts_sensitive_args_before_persisting():
    """Regression (CodeRabbit, PR #135): _trace_turn()'s redaction only
    protected the tracer/admin_activity broadcast — _record_exec() (used for
    self-reflection, a completely separate persistence path to K_EXECS) still
    wrote raw args verbatim, so a credential could reach self-reflection even
    after the other two paths were fixed."""
    mind = AriaMind()
    saved = {}

    fake_cache = MagicMock()
    fake_cache.get = AsyncMock(return_value=None)

    async def fake_set(key, value, ttl_seconds=None):
        saved[key] = value
        return True

    fake_cache.set = AsyncMock(side_effect=fake_set)

    with patch.object(mind, "_cache_client", return_value=fake_cache):
        await mind._record_exec(
            "send_email",
            {"to": "someone@example.com", "api_key": "sk-real-secret"},
            "sent",
            True,
        )

    record = saved[mind.K_EXECS][0]
    assert "sk-real-secret" not in record["in"]
    assert "[REDACTED]" in record["in"]


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
async def test_handle_traces_the_executed_retry_args_not_the_original_plan_args():
    """End-to-end regression (CodeRabbit, PR #131): a full AriaMind.handle()
    call, where the planned tool_args fail once and _adapt_args_generic
    corrects them on retry, must trace the args that actually produced the
    result — not the original plan's args, which were never executed."""
    plan_args = {"product_name": "widget", "category": ""}
    adapted_args = {"product_name": "Widget Pro", "category": "gadgets"}

    async def fake_reason(*a, **k):
        return {"tool": "optimize_product_seo", "tool_args": plan_args, "reply": ""}

    calls = []

    async def fake_execute_tool(tool, args, attempt=0, email=""):
        calls.append(dict(args))
        if attempt == 0:
            return "Error: category cannot be empty", {}
        return "SEO optimized successfully", {}

    fake_adapt_ai = AsyncMock()
    fake_adapt_ai.complete_json = AsyncMock(return_value={"tool_args": adapted_args})

    fake_tracer = AsyncMock()
    clean_moderation = ModerationResult(blocked=False, layer="llm")

    mind = AriaMind()
    with ExitStack() as stack:
        mock_ks = stack.enter_context(patch("apps.core.safety.guardrails.get_kill_switch"))
        stack.enter_context(
            patch(
                "apps.core.safety.guardrails.moderate_input",
                AsyncMock(return_value=clean_moderation),
            )
        )
        stack.enter_context(
            patch("apps.evaluation.phoenix.tracer.get_cognition_tracer", return_value=fake_tracer)
        )
        stack.enter_context(patch.object(mind, "_reason", fake_reason))
        stack.enter_context(patch.object(mind, "_execute_tool", fake_execute_tool))
        stack.enter_context(patch.object(mind, "_ai_client", return_value=fake_adapt_ai))
        stack.enter_context(patch("apps.core.cognition.aria_mind.asyncio.sleep", AsyncMock()))
        stack.enter_context(patch.object(mind, "_load_history", AsyncMock(return_value=[])))
        stack.enter_context(patch.object(mind, "_load_state", AsyncMock(return_value={})))
        stack.enter_context(patch.object(mind, "_load_goals", AsyncMock(return_value=[])))
        stack.enter_context(patch.object(mind, "_load_learned", AsyncMock(return_value=[])))
        stack.enter_context(patch.object(mind, "_store_interaction", AsyncMock()))
        stack.enter_context(patch.object(mind, "_evolve_state", AsyncMock()))
        stack.enter_context(patch.object(mind, "_maybe_reflect", AsyncMock()))
        stack.enter_context(patch.object(mind, "_record_exec", AsyncMock()))
        mock_ks.return_value.is_active = AsyncMock(return_value=False)

        await mind.handle("optimize my widget listing", "chat-1", email="owner@example.com")

    assert len(calls) == 2
    assert calls[0] == plan_args
    assert calls[1] == adapted_args
    fake_tracer.record.assert_awaited_once()
    kwargs = fake_tracer.record.call_args.kwargs
    assert kwargs["tool_args"] == adapted_args
    assert kwargs["tool_args"] != plan_args


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
