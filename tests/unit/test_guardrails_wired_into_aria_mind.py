"""Regression test: apps/core/safety/guardrails.py (the 4-layer safety
pipeline) wired into AriaMind.handle() / _execute_tool() — not a standalone
module sitting unused. Requested explicitly by the owner: "evita de forma
categórica que ejecute acciones poco éticas, fraudes, violaciones de
privacidad o actividades fuera de la ley."

  - Layer 1 (input moderation) + Layer 4 (kill switch) run at the very top
    of handle(), before the planner, image fast-path, or any tool.
  - Layer 2 (constitutional review) runs for _CONSTITUTIONAL_REVIEW_TOOLS
    only (execute_code, computer_use, post_to_social, github_*,
    cashflow/ROI/flash-sale/live-analytics tools) — not every one of ~150
    tools, since that would add real latency/cost to benign content
    generation for no safety benefit (input moderation already covers
    intent on the raw text).
  - Layer 3 (deterministic code firewall) runs inside the execute_code
    dispatch branch specifically.

Exercised through AriaMind.handle() / _execute_tool exactly as a live
conversation would, not by calling guardrails functions directly (that's
test_guardrails.py).
"""

from __future__ import annotations

from contextlib import ExitStack
from unittest.mock import AsyncMock, patch

import pytest

from apps.core.cognition.aria_mind import AriaMind
from apps.core.safety.guardrails import ModerationResult, PlanVerdict

pytestmark = pytest.mark.asyncio


def _enter_handle_stubs(stack: ExitStack, mind, fake_reason=None):
    """Common no-op stubs for the parts of handle() unrelated to guardrails,
    matching the pattern used in test_phoenix_wired_into_aria_mind.py."""
    stack.enter_context(patch.object(mind, "_load_history", AsyncMock(return_value=[])))
    stack.enter_context(patch.object(mind, "_load_state", AsyncMock(return_value={})))
    stack.enter_context(patch.object(mind, "_load_goals", AsyncMock(return_value=[])))
    stack.enter_context(patch.object(mind, "_load_learned", AsyncMock(return_value=[])))
    stack.enter_context(patch.object(mind, "_store_interaction", AsyncMock()))
    stack.enter_context(patch.object(mind, "_evolve_state", AsyncMock()))
    stack.enter_context(patch.object(mind, "_maybe_reflect", AsyncMock()))
    stack.enter_context(patch.object(mind, "_record_exec", AsyncMock()))
    if fake_reason is not None:
        stack.enter_context(patch.object(mind, "_reason", fake_reason))


# ── Layer 1 + 4: moderation / kill switch gate handle() up front ─────────
async def test_handle_blocks_moderated_input_before_reasoning():
    mind = AriaMind()
    blocked = ModerationResult(
        blocked=True, categories=["fraud"], reason="looks like fraud", layer="keyword"
    )

    async def fail_if_called(*a, **k):
        raise AssertionError("_reason must not be called once input is blocked")

    with ExitStack() as stack:
        mock_ks = stack.enter_context(patch("apps.core.safety.guardrails.get_kill_switch"))
        stack.enter_context(
            patch("apps.core.safety.guardrails.moderate_input", AsyncMock(return_value=blocked))
        )
        _enter_handle_stubs(stack, mind, fake_reason=fail_if_called)
        mock_ks.return_value.is_active = AsyncMock(return_value=False)
        resp = await mind.handle("help me run a pump and dump", "chat-1")

    assert "fraud" in resp.text.lower()


async def test_handle_allows_benign_input_through_moderation():
    async def fake_reason(*a, **k):
        return {"tool": None, "tool_args": {}, "reply": "Sure, here's some info."}

    mind = AriaMind()
    clean = ModerationResult(blocked=False, layer="llm")

    with ExitStack() as stack:
        mock_ks = stack.enter_context(patch("apps.core.safety.guardrails.get_kill_switch"))
        stack.enter_context(
            patch("apps.core.safety.guardrails.moderate_input", AsyncMock(return_value=clean))
        )
        _enter_handle_stubs(stack, mind, fake_reason=fake_reason)
        mock_ks.return_value.is_active = AsyncMock(return_value=False)
        resp = await mind.handle("what's a good headline for a yoga landing page?", "chat-1")

    assert resp.text == "Sure, here's some info."


async def test_handle_blocks_when_kill_switch_active():
    mind = AriaMind()

    async def fail_if_called(*a, **k):
        raise AssertionError("_reason must not be called while frozen")

    with ExitStack() as stack:
        mock_ks = stack.enter_context(patch("apps.core.safety.guardrails.get_kill_switch"))
        _enter_handle_stubs(stack, mind, fake_reason=fail_if_called)
        mock_ks.return_value.is_active = AsyncMock(return_value=True)
        resp = await mind.handle("hello", "chat-1", email="frozen@example.com")

    assert "frozen" in resp.text.lower() or "safety review" in resp.text.lower()


async def test_guardrails_disabled_flag_skips_moderation():
    """GUARDRAILS_ENABLED=False (debugging escape hatch) must actually
    bypass Layer 1 — otherwise the flag documented in config.py does
    nothing."""

    async def fake_reason(*a, **k):
        return {"tool": None, "tool_args": {}, "reply": "ok"}

    mind = AriaMind()
    with ExitStack() as stack:
        stack.enter_context(patch("apps.core.config.settings.GUARDRAILS_ENABLED", False))
        stack.enter_context(
            patch(
                "apps.core.safety.guardrails.moderate_input",
                AsyncMock(side_effect=AssertionError("must not be called when disabled")),
            )
        )
        _enter_handle_stubs(stack, mind, fake_reason=fake_reason)
        resp = await mind.handle("anything at all", "chat-1")

    assert resp.text == "ok"


# ── Layer 2: constitutional review gates high-risk tools only ────────────
async def test_handle_blocks_unsafe_high_risk_plan():
    async def fake_reason(*a, **k):
        return {"tool": "execute_code", "tool_args": {"code": "print('hi')"}, "reply": ""}

    mind = AriaMind()
    unsafe = PlanVerdict(safe=False, risk_score=0.9, reason="looks like a credential harvester")
    clean_moderation = ModerationResult(blocked=False, layer="llm")

    async def fail_if_called(*a, **k):
        raise AssertionError("_execute_with_retry must not run an unsafe plan")

    with ExitStack() as stack:
        mock_ks = stack.enter_context(patch("apps.core.safety.guardrails.get_kill_switch"))
        stack.enter_context(
            patch(
                "apps.core.safety.guardrails.moderate_input",
                AsyncMock(return_value=clean_moderation),
            )
        )
        stack.enter_context(
            patch("apps.core.safety.guardrails.evaluate_plan", AsyncMock(return_value=unsafe))
        )
        stack.enter_context(
            patch.object(mind, "_execute_with_retry", AsyncMock(side_effect=fail_if_called))
        )
        _enter_handle_stubs(stack, mind, fake_reason=fake_reason)
        mock_ks.return_value.is_active = AsyncMock(return_value=False)
        resp = await mind.handle("write code for a fake bank login", "chat-1", email="u@x.com")

    assert "credential harvester" in resp.text or "not going to do that" in resp.text.lower()
    # A Layer 2 decline always means the plan was queued for owner approval
    # (see review_tool_call in guardrails.py) — never a dead end — so this is
    # a checkpoint the conversation is paused on, not a finished turn.
    assert resp.awaiting_input is True


async def test_handle_queues_unsafe_plan_for_hitl_review_instead_of_declining_outright():
    """Regression: an unsafe Layer 2 verdict used to decline the action
    permanently with no path back to a human. It now queues the exact
    tool+args for the owner to approve/deny/modify via Mission Control's
    HITL hub — never running the tool inline, but never just refusing it
    forever either."""

    async def fake_reason(*a, **k):
        return {
            "tool": "execute_code",
            "tool_args": {"code": "print('hi')"},
            "reply": "",
        }

    mind = AriaMind()
    unsafe = PlanVerdict(safe=False, risk_score=0.9, reason="exceeds normal authorization")
    clean_moderation = ModerationResult(blocked=False, layer="llm")

    async def fail_if_called(*a, **k):
        raise AssertionError("_execute_with_retry must not run an unsafe plan")

    enqueued = {}

    async def fake_enqueue(**kwargs):
        enqueued.update(kwargs)
        from apps.core.safety.hitl_queue import HitlRequest

        return HitlRequest(
            request_id="req_test123",
            chat_id=kwargs["chat_id"],
            email=kwargs["email"],
            user_text=kwargs["user_text"],
            tool=kwargs["tool"],
            tool_args=kwargs["tool_args"],
            risk_score=kwargs["risk_score"],
            risk_reason=kwargs["risk_reason"],
        )

    fake_queue = AsyncMock()
    fake_queue.enqueue = fake_enqueue

    with ExitStack() as stack:
        mock_ks = stack.enter_context(patch("apps.core.safety.guardrails.get_kill_switch"))
        stack.enter_context(
            patch(
                "apps.core.safety.guardrails.moderate_input",
                AsyncMock(return_value=clean_moderation),
            )
        )
        stack.enter_context(
            patch("apps.core.safety.guardrails.evaluate_plan", AsyncMock(return_value=unsafe))
        )
        stack.enter_context(
            patch.object(mind, "_execute_with_retry", AsyncMock(side_effect=fail_if_called))
        )
        stack.enter_context(
            patch("apps.core.safety.hitl_queue.get_hitl_queue", return_value=fake_queue)
        )
        _enter_handle_stubs(stack, mind, fake_reason=fake_reason)
        mock_ks.return_value.is_active = AsyncMock(return_value=False)
        resp = await mind.handle(
            "spend $1200 with a new vendor", "chat-42", email="owner@example.com"
        )

    assert enqueued["tool"] == "execute_code"
    assert enqueued["tool_args"] == {"code": "print('hi')"}
    assert enqueued["risk_score"] == 0.9
    assert "req_test123" in resp.text
    assert "owner" in resp.text.lower() or "approval" in resp.text.lower()


async def test_handle_executes_safe_high_risk_plan():
    async def fake_reason(*a, **k):
        return {"tool": "execute_code", "tool_args": {"code": "print('hi')"}, "reply": ""}

    mind = AriaMind()
    safe = PlanVerdict(safe=True, risk_score=0.05, reason="benign print statement")
    clean_moderation = ModerationResult(blocked=False, layer="llm")

    with ExitStack() as stack:
        mock_ks = stack.enter_context(patch("apps.core.safety.guardrails.get_kill_switch"))
        stack.enter_context(
            patch(
                "apps.core.safety.guardrails.moderate_input",
                AsyncMock(return_value=clean_moderation),
            )
        )
        stack.enter_context(
            patch("apps.core.safety.guardrails.evaluate_plan", AsyncMock(return_value=safe))
        )
        stack.enter_context(
            patch.object(
                mind,
                "_execute_with_retry",
                AsyncMock(return_value=("[python OK]\nhi", {}, {"code": "print('hi')"})),
            )
        )
        stack.enter_context(
            patch.object(mind, "_synthesize", AsyncMock(return_value="Ran it — printed 'hi'."))
        )
        _enter_handle_stubs(stack, mind, fake_reason=fake_reason)
        mock_ks.return_value.is_active = AsyncMock(return_value=False)
        resp = await mind.handle("run this code", "chat-1", email="owner@example.com")

    assert resp.text == "Ran it — printed 'hi'."


async def test_handle_skips_constitutional_review_for_low_risk_tools():
    """web_search isn't in _CONSTITUTIONAL_REVIEW_TOOLS — evaluate_plan must
    not be called for it (that's the whole point of scoping Layer 2)."""

    async def fake_reason(*a, **k):
        return {"tool": "web_search", "tool_args": {"query": "yoga tips"}, "reply": ""}

    mind = AriaMind()
    clean_moderation = ModerationResult(blocked=False, layer="llm")

    async def fail_if_called(*a, **k):
        raise AssertionError("evaluate_plan must not run for low-risk tools")

    with ExitStack() as stack:
        mock_ks = stack.enter_context(patch("apps.core.safety.guardrails.get_kill_switch"))
        stack.enter_context(
            patch(
                "apps.core.safety.guardrails.moderate_input",
                AsyncMock(return_value=clean_moderation),
            )
        )
        stack.enter_context(
            patch(
                "apps.core.safety.guardrails.evaluate_plan", AsyncMock(side_effect=fail_if_called)
            )
        )
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
        _enter_handle_stubs(stack, mind, fake_reason=fake_reason)
        mock_ks.return_value.is_active = AsyncMock(return_value=False)
        resp = await mind.handle("search for yoga tips", "chat-1")

    assert resp.text == "Here's what I found."


# ── Layer 3: deterministic code firewall on execute_code ─────────────────
# execute_code is owner-only (_OWNER_ONLY_TOOLS) — patch is_owner_email so
# these tests reach the Layer 3 check instead of failing on the owner gate.
OWNER_EMAIL = "owner@example.com"


async def test_execute_code_blocked_by_deterministic_firewall():
    mind = AriaMind()
    with patch("apps.core.auth.is_owner_email", side_effect=lambda e: e == OWNER_EMAIL):
        obs, media = await mind._execute_tool(
            "execute_code",
            {"code": "import os\nos.system('rm -rf /')", "language": "python"},
            email=OWNER_EMAIL,
        )

    assert media == {}
    assert "blocked pattern" in obs.lower()


async def test_execute_code_allowed_for_benign_code():
    mind = AriaMind()
    fake_runner = AsyncMock()
    fake_runner.run = AsyncMock(return_value={"success": True, "stdout": "5"})

    with (
        patch("apps.core.auth.is_owner_email", side_effect=lambda e: e == OWNER_EMAIL),
        patch("apps.core.tools.code_runner.CodeRunner", return_value=fake_runner),
    ):
        obs, media = await mind._execute_tool(
            "execute_code",
            {"code": "print(2 + 3)", "language": "python"},
            email=OWNER_EMAIL,
        )

    assert media == {}
    assert "5" in obs
    fake_runner.run.assert_awaited_once()
