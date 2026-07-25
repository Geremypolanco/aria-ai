"""Regression test: a security-audit pass found WorkflowEngine.run() called
AriaMind._execute_tool directly (apps/core/tools/workflow_engine.py), which
completely skipped Guardrails Layer 2 (constitutional plan review) — that
check only lived inline in AriaMind.handle(), the normal chat path, never
inside _execute_tool itself. It also never passed the running user's email
through, so every workflow step executed with an effectively anonymous
identity (email="") regardless of who created/ran the workflow.

Two fixes, both covered here:
  1. guardrails.review_tool_call() / CONSTITUTIONAL_REVIEW_TOOLS moved out
     of AriaMind into apps/core/safety/guardrails.py as the single shared
     gate, so WorkflowEngine.run() can call the exact same check
     AriaMind.handle() uses — not a second, driftable copy of the logic.
  2. WorkflowEngine.run(workflow_id, email=...) threads the caller's real
     identity through to both the guardrails review and _execute_tool
     (needed for _OWNER_ONLY_TOOLS gating to work at all inside a workflow).

Exercised at the WorkflowEngine level (not just aria_mind.py's dispatch
case), since the bypass was inside WorkflowEngine.run() itself.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from apps.core.safety.guardrails import CONSTITUTIONAL_REVIEW_TOOLS, PlanVerdict
from apps.core.tools.workflow_engine import Workflow, WorkflowEngine, WorkflowStep

pytestmark = pytest.mark.asyncio

OWNER_EMAIL = "owner@aria.test"


def _engine_with_workflow(tool: str, args: dict) -> WorkflowEngine:
    engine = WorkflowEngine()
    engine._loaded = True
    wf = Workflow(
        id="wf1",
        name="Test workflow",
        description="test",
        steps=[WorkflowStep(tool=tool, args=args, description="a step")],
    )
    engine._workflows["wf1"] = wf
    return engine


async def test_record_cashflow_entry_is_in_the_shared_review_set():
    # Sanity check the set this whole test file depends on actually contains
    # the tool the exploit scenario used — if this ever drifted, the tests
    # below would still pass for the wrong reason (nothing to review).
    assert "record_cashflow_entry" in CONSTITUTIONAL_REVIEW_TOOLS


async def test_workflow_step_goes_through_layer_2_and_gets_blocked():
    """The literal bug: before the fix, this tool call would run with no
    constitutional review at all."""
    engine = _engine_with_workflow(
        "record_cashflow_entry", {"type": "income", "amount": 999999, "category": "sales"}
    )
    unsafe = PlanVerdict(safe=False, risk_score=0.95, reason="implausible amount, likely abuse")

    with (
        patch("apps.core.safety.guardrails.evaluate_plan", AsyncMock(return_value=unsafe)),
        patch("apps.core.cognition.aria_mind.get_aria_mind") as mock_get_mind,
    ):
        result = await engine.run("wf1", email=OWNER_EMAIL)

    assert result["results"][0]["success"] is False
    assert "implausible amount" in result["results"][0]["error"]
    # The tool must never have actually been executed.
    mock_get_mind.return_value._execute_tool.assert_not_called()


async def test_workflow_step_proceeds_when_layer_2_approves():
    engine = _engine_with_workflow(
        "record_cashflow_entry", {"type": "income", "amount": 500, "category": "sales"}
    )
    safe = PlanVerdict(safe=True, risk_score=0.05, reason="ordinary income entry")

    fake_mind = AsyncMock()
    fake_mind._execute_tool = AsyncMock(return_value=("Recorded income: $500.00 (sales)", {}))

    with (
        patch("apps.core.safety.guardrails.evaluate_plan", AsyncMock(return_value=safe)),
        patch("apps.core.cognition.aria_mind.get_aria_mind", return_value=fake_mind),
    ):
        result = await engine.run("wf1", email=OWNER_EMAIL)

    assert result["results"][0]["success"] is True
    fake_mind._execute_tool.assert_awaited_once_with(
        "record_cashflow_entry",
        {"type": "income", "amount": 500, "category": "sales"},
        email=OWNER_EMAIL,
    )


async def test_workflow_step_for_non_review_tool_skips_evaluate_plan_entirely():
    """web_search isn't in CONSTITUTIONAL_REVIEW_TOOLS — same latency/cost
    argument as the normal chat path: only consequential tools pay for the
    extra LLM call."""
    engine = _engine_with_workflow("web_search", {"query": "yoga tips"})

    fake_mind = AsyncMock()
    fake_mind._execute_tool = AsyncMock(return_value=("some results", {}))

    async def fail_if_called(*a, **k):
        raise AssertionError("evaluate_plan must not run for a non-reviewed tool")

    with (
        patch("apps.core.safety.guardrails.evaluate_plan", AsyncMock(side_effect=fail_if_called)),
        patch("apps.core.cognition.aria_mind.get_aria_mind", return_value=fake_mind),
    ):
        result = await engine.run("wf1", email=OWNER_EMAIL)

    assert result["results"][0]["success"] is True


async def test_workflow_run_threads_email_to_execute_tool_for_owner_gating():
    """Before the fix, _execute_tool was always called with the default
    email="" — meaning even the real owner's own workflow could never reach
    an owner-only tool like execute_code from inside a workflow."""
    engine = _engine_with_workflow("execute_code", {"code": "print(1)", "language": "python"})
    safe = PlanVerdict(safe=True, risk_score=0.0, reason="benign")

    fake_mind = AsyncMock()
    fake_mind._execute_tool = AsyncMock(return_value=("[python OK]\n1", {}))

    with (
        patch("apps.core.safety.guardrails.evaluate_plan", AsyncMock(return_value=safe)),
        patch("apps.core.cognition.aria_mind.get_aria_mind", return_value=fake_mind),
    ):
        await engine.run("wf1", email=OWNER_EMAIL)

    _, kwargs = fake_mind._execute_tool.call_args
    assert kwargs.get("email") == OWNER_EMAIL


async def test_review_tool_call_returns_none_when_guardrails_disabled():
    from apps.core.safety import guardrails

    with patch("apps.core.config.settings.GUARDRAILS_ENABLED", False):
        decline = await guardrails.review_tool_call(
            "execute_code", {"code": "import os; os.system('rm -rf /')"}, email=OWNER_EMAIL
        )

    assert decline is None


async def test_review_tool_call_returns_none_for_tools_outside_the_review_set():
    from apps.core.safety import guardrails

    async def fail_if_called(*a, **k):
        raise AssertionError("evaluate_plan must not run for web_search")

    with patch("apps.core.safety.guardrails.evaluate_plan", AsyncMock(side_effect=fail_if_called)):
        decline = await guardrails.review_tool_call("web_search", {"query": "x"})

    assert decline is None


@pytest.mark.parametrize(
    "tool",
    [
        "recover_abandoned_cart",
        "create_flash_sale",
        "create_product_bundle",
        "recommend_products",
        "shopify_revenue_dashboard",
        "optimize_product_seo",
        "audit_seo_keywords",
        "create_upsell_offer",
        "optimize_shopify_checkout",
        "create_post_purchase_flow",
        "shopify_store_status",
        "shopify_live_analytics",
        "track_roi",
        "update_roi_returns",
        "roi_summary",
        "record_cashflow_entry",
        "cashflow_summary",
        "forecast_cashflow",
    ],
)
async def test_shopify_and_finance_tools_are_owner_only(tool):
    """Every tool a security audit flagged as writing to a single Redis key
    shared by all users (or reading the owner's real Shopify API
    credentials) must be in AriaMind._OWNER_ONLY_TOOLS. A regression here
    would silently reopen the data-corruption/exposure gap."""
    from apps.core.cognition.aria_mind import AriaMind

    assert tool in AriaMind._OWNER_ONLY_TOOLS
