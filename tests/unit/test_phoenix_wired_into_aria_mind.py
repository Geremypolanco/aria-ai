"""Regression test: apps/evaluation/phoenix/ (CognitionTracer + AIEvaluator)
had zero live callers — a complete observability implementation (per-turn
tracing with quality/hallucination heuristics, plus a separate multi-
dimensional response evaluator) sitting unused.

Unlike the other audited-but-disconnected modules, these aren't user-invoked
chat tools by nature:
  - CognitionTracer is wired as passive instrumentation: AriaMind.handle()
    now calls _trace_turn() at every exit point (image fast-path, tool
    execution, plain-text reply), best-effort and swallowing all errors so a
    tracing failure can never affect the actual reply the user receives.
  - AIEvaluator is exposed as an explicit tool, evaluate_ai_response, for
    on-demand quality scoring of any content — general-purpose, unlike the
    marketing-specific score_copy_persuasion.
  - ai_performance_report reads CognitionTracer's aggregate analytics().
    It's an internal diagnostic (like /status), so it's owner-gated inline
    rather than through a chat "tool" a free-tier account should reach.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest

from apps.core.cognition.aria_mind import AriaMind
from apps.core.safety.guardrails import ModerationResult
from apps.evaluation.phoenix.evaluator import AIEvaluator
from apps.evaluation.phoenix.tracer import CognitionTracer

pytestmark = pytest.mark.asyncio


class _FakeCache:
    def __init__(self):
        self._store = {}

    async def get(self, key):
        return self._store.get(key)

    async def set(self, key, value, ttl_seconds=3600):
        self._store[key] = value
        return True


async def test_evaluate_ai_response_reachable_from_tool_dispatch():
    evaluator = AIEvaluator()
    with patch("apps.evaluation.phoenix.evaluator.get_ai_evaluator", return_value=evaluator):
        mind = AriaMind()
        obs, media = await mind._execute_tool(
            "evaluate_ai_response",
            {"content": "This is a specific, actionable report with 42 data points."},
        )

    assert media == {}
    assert "Overall quality" in obs
    assert "relevance" in obs.lower()


async def test_evaluate_ai_response_requires_content():
    mind = AriaMind()
    obs, media = await mind._execute_tool("evaluate_ai_response", {})

    assert media == {}
    assert "content" in obs.lower()


async def test_ai_performance_report_blocked_for_non_owner(monkeypatch):
    monkeypatch.setattr("apps.core.config.settings.OWNER_EMAIL", "owner@example.com")
    mind = AriaMind()
    obs, media = await mind._execute_tool(
        "ai_performance_report", {}, email="random-user@example.com"
    )

    assert media == {}
    assert "owner" in obs.lower()


async def test_ai_performance_report_reachable_for_owner(monkeypatch):
    monkeypatch.setattr("apps.core.config.settings.OWNER_EMAIL", "owner@example.com")
    tracer = CognitionTracer()
    fake_cache = _FakeCache()
    with (
        patch("apps.evaluation.phoenix.tracer.get_cache", return_value=fake_cache),
        patch("apps.evaluation.phoenix.tracer.get_cognition_tracer", return_value=tracer),
    ):
        await tracer.record(
            agent_name="aria_mind",
            task_type="conversation",
            prompt="hi",
            response="hello",
            latency_ms=120.0,
            success=True,
        )
        mind = AriaMind()
        obs, media = await mind._execute_tool(
            "ai_performance_report", {}, email="owner@example.com"
        )

    assert media == {}
    assert "AI performance" in obs
    assert "1 traces" in obs


async def test_ai_performance_report_empty_state(monkeypatch):
    monkeypatch.setattr("apps.core.config.settings.OWNER_EMAIL", "owner@example.com")
    tracer = CognitionTracer()
    fake_cache = _FakeCache()
    with (
        patch("apps.evaluation.phoenix.tracer.get_cache", return_value=fake_cache),
        patch("apps.evaluation.phoenix.tracer.get_cognition_tracer", return_value=tracer),
    ):
        mind = AriaMind()
        obs, media = await mind._execute_tool(
            "ai_performance_report", {}, email="owner@example.com"
        )

    assert media == {}
    assert "no traced" in obs.lower()


async def test_handle_traces_text_only_turn():
    tracer = CognitionTracer()
    fake_cache = _FakeCache()

    async def fake_reason(*a, **k):
        return {"tool": None, "tool_args": {}, "reply": "hello there"}

    mind = AriaMind()
    with (
        patch("apps.evaluation.phoenix.tracer.get_cache", return_value=fake_cache),
        patch("apps.evaluation.phoenix.tracer.get_cognition_tracer", return_value=tracer),
        patch.object(mind, "_reason", fake_reason),
        patch.object(mind, "_load_history", AsyncMock(return_value=[])),
        patch.object(mind, "_load_state", AsyncMock(return_value={})),
        patch.object(mind, "_load_goals", AsyncMock(return_value=[])),
        patch.object(mind, "_load_learned", AsyncMock(return_value=[])),
        patch.object(mind, "_store_interaction", AsyncMock()),
        patch.object(mind, "_evolve_state", AsyncMock()),
        patch.object(mind, "_maybe_reflect", AsyncMock()),
    ):
        resp = await mind.handle("hi", "chat-1")

    assert resp.text == "hello there"
    traces = await tracer.recent_traces()
    assert len(traces) == 1
    assert traces[0]["task_type"] == "conversation"
    assert traces[0]["response"] == "hello there"
    assert traces[0]["success"] is True


async def test_handle_broadcasts_turn_to_admin_activity_channel():
    """Every turn is also published live to the "admin_activity" log_bus
    channel — the feed behind the admin console's real-time activity view
    (GET /admin/api/activity/stream). This must fire alongside, not instead
    of, CognitionTracer recording."""
    tracer = CognitionTracer()
    fake_cache = _FakeCache()

    async def fake_reason(*a, **k):
        return {"tool": None, "tool_args": {}, "reply": "hello there"}

    mind = AriaMind()
    published: list[tuple[str, str]] = []

    async def fake_publish(channel, message, **kwargs):
        published.append((channel, message))

    with (
        patch("apps.evaluation.phoenix.tracer.get_cache", return_value=fake_cache),
        patch("apps.evaluation.phoenix.tracer.get_cognition_tracer", return_value=tracer),
        patch("apps.core.scale.log_bus.publish", side_effect=fake_publish),
        # Isolate from the live Guardrails Layer 1 pipeline (apps/core/safety/
        # guardrails.py) — this test is about _trace_turn's broadcast, not
        # moderation, and moderate_input would otherwise hit the (unconfigured
        # in tests) AI classifier and add its own admin_activity message.
        patch(
            "apps.core.safety.guardrails.moderate_input",
            AsyncMock(return_value=ModerationResult(blocked=False)),
        ),
        patch("apps.core.safety.guardrails.get_kill_switch") as mock_ks,
        patch.object(mind, "_reason", fake_reason),
        patch.object(mind, "_load_history", AsyncMock(return_value=[])),
        patch.object(mind, "_load_state", AsyncMock(return_value={})),
        patch.object(mind, "_load_goals", AsyncMock(return_value=[])),
        patch.object(mind, "_load_learned", AsyncMock(return_value=[])),
        patch.object(mind, "_store_interaction", AsyncMock()),
        patch.object(mind, "_evolve_state", AsyncMock()),
        patch.object(mind, "_maybe_reflect", AsyncMock()),
    ):
        mock_ks.return_value.is_active = AsyncMock(return_value=False)
        resp = await mind.handle("hi", "chat-1", email="watcher@example.com")

    assert resp.text == "hello there"
    assert len(published) == 1
    channel, message = published[0]
    assert channel == "admin_activity"
    payload = json.loads(message)
    assert payload["email"] == "watcher@example.com"
    assert payload["chat_id"] == "chat-1"
    assert payload["response"].startswith("hello there")
    assert payload["success"] is True


async def test_handle_tracing_failure_never_breaks_the_reply():
    """_trace_turn swallows all errors — a broken tracer must not surface as
    a user-facing failure."""

    async def fake_reason(*a, **k):
        return {"tool": None, "tool_args": {}, "reply": "hello there"}

    mind = AriaMind()
    with (
        patch(
            "apps.evaluation.phoenix.tracer.get_cognition_tracer",
            side_effect=RuntimeError("tracer exploded"),
        ),
        patch.object(mind, "_reason", fake_reason),
        patch.object(mind, "_load_history", AsyncMock(return_value=[])),
        patch.object(mind, "_load_state", AsyncMock(return_value={})),
        patch.object(mind, "_load_goals", AsyncMock(return_value=[])),
        patch.object(mind, "_load_learned", AsyncMock(return_value=[])),
        patch.object(mind, "_store_interaction", AsyncMock()),
        patch.object(mind, "_evolve_state", AsyncMock()),
        patch.object(mind, "_maybe_reflect", AsyncMock()),
    ):
        resp = await mind.handle("hi", "chat-1")

    assert resp.text == "hello there"
