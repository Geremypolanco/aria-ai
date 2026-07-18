"""
Unit tests for ARIA Dynamic Workflows (apps/core/orchestration/dynamic_workflow.py).

The whole engine depends only on a `.complete(...)` interface, so every test runs
with a network-free FakeClient — no HF/Anthropic/OpenAI calls. We assert:

  - planning parses JSON into typed SubTasks and routes kinds → model tiers
  - a bad plan degrades to a single-task flow instead of crashing
  - subagents run in parallel and their outputs are synthesized
  - adversarial verification flags a flawed result and triggers a single repair
  - token accounting sums across plan + subagents + verify + synth
  - an empty goal is handled gracefully
"""

from __future__ import annotations

import json

from apps.core.orchestration.dynamic_workflow import (
    DynamicWorkflow,
    SubTask,
    TaskKind,
)
from apps.core.tools.ai_client import AIModel, AIResponse


class FakeClient:
    """Deterministic stand-in for AriaAIClient.

    Routes by `agent_name` so each phase returns a scripted response. Records
    every call so tests can assert routing (which AIModel each phase used).
    """

    def __init__(
        self, plan: dict | None = None, verifier: dict | None = None, clarifier: dict | None = None
    ):
        self._plan = plan
        self._verifier = verifier
        # Default: "ready" with 0 tokens so the clarify gate is a no-op for the
        # execution/token tests. A test can pass clarifier={"ready":false,...}.
        self._clarifier = clarifier
        self.calls: list[dict] = []

    async def complete(
        self,
        system: str,
        user: str,
        model: AIModel = AIModel.STRATEGY,
        max_tokens: int = 2000,
        temperature: float = 0.7,
        json_mode: bool = False,
        agent_name: str = "aria",
    ) -> AIResponse:
        self.calls.append({"agent": agent_name, "model": model, "user": user})

        if agent_name == "workflow.clarify":
            content = json.dumps(self._clarifier or {"ready": True})
            return _resp(content, tokens=0)

        if agent_name == "workflow.planner":
            content = json.dumps(self._plan) if self._plan is not None else "not json at all"
            return _resp(content, tokens=10)

        if agent_name.startswith("workflow.verify."):
            content = json.dumps(self._verifier or {"ok": True, "critique": ""})
            return _resp(content, tokens=5)

        if agent_name.startswith("workflow.repair."):
            return _resp("REPAIRED OUTPUT", tokens=7)

        if agent_name.startswith("workflow.") and agent_name.endswith(".synth"):
            return _resp("FINAL SYNTHESIS", tokens=9)
        if agent_name == "workflow.synth":
            return _resp("FINAL SYNTHESIS", tokens=9)

        # A subagent (workflow.t1, workflow.t2, ...)
        return _resp(f"output for {agent_name}", tokens=8)


def _resp(content: str, tokens: int = 0) -> AIResponse:
    return AIResponse(
        content=content,
        provider="huggingface",  # type: ignore[arg-type]
        model="fake/model",
        tokens_used=tokens,
        latency_ms=1,
        success=True,
    )


def _plan(*kinds: str) -> dict:
    return {
        "subtasks": [
            {"title": f"Task {i + 1}", "prompt": f"do thing {i + 1}", "kind": k}
            for i, k in enumerate(kinds)
        ]
    }


# ── PLANNING ────────────────────────────────────────────────────────────────


async def test_plan_parses_and_routes_kinds():
    client = FakeClient(plan=_plan("reason", "code", "creative"))
    wf = DynamicWorkflow(client, verify=False)
    tasks = await wf._plan("build a launch", None)

    assert [t.kind for t in tasks] == [TaskKind.REASON, TaskKind.CODE, TaskKind.CREATIVE]
    assert tasks[0].model() == AIModel.REASONING
    assert tasks[1].model() == AIModel.CODE
    assert tasks[2].model() == AIModel.CREATIVE
    assert all(t.id and t.prompt for t in tasks)


async def test_bad_plan_degrades_to_single_task():
    client = FakeClient(plan=None)  # planner returns non-JSON
    wf = DynamicWorkflow(client, verify=False)
    tasks = await wf._plan("just do it", None)

    assert len(tasks) == 1
    assert tasks[0].prompt == "just do it"
    assert tasks[0].kind == TaskKind.REASON


async def test_plan_caps_subtasks():
    client = FakeClient(plan=_plan(*(["fast"] * 20)))  # 20 requested
    wf = DynamicWorkflow(client, verify=False)
    tasks = await wf._plan("many", None)
    assert len(tasks) <= 6


async def test_unknown_kind_falls_back_to_research():
    client = FakeClient(plan={"subtasks": [{"title": "x", "prompt": "p", "kind": "banana"}]})
    wf = DynamicWorkflow(client, verify=False)
    tasks = await wf._plan("goal", None)
    assert tasks[0].kind == TaskKind.RESEARCH


# ── FULL RUN ────────────────────────────────────────────────────────────────


async def test_run_executes_parallel_and_synthesizes():
    client = FakeClient(plan=_plan("research", "research"))
    wf = DynamicWorkflow(client, verify=False)
    result = await wf.run("compare two options")

    assert result.ok
    assert result.synthesis == "FINAL SYNTHESIS"
    assert len(result.results) == 2
    assert all(r.ok for r in result.results)
    # planner(10) + 2 subagents(8+8) + synth(9) = 35
    assert result.total_tokens == 10 + 8 + 8 + 9
    assert result.duration_ms >= 0


async def test_single_subtask_skips_synthesis_call():
    client = FakeClient(plan=_plan("reason"))
    wf = DynamicWorkflow(client, verify=False)
    result = await wf.run("one thing")

    # With a single usable result there is nothing to integrate: output passes through.
    assert result.synthesis == "output for workflow.t1"
    assert not any(c["agent"] == "workflow.synth" for c in client.calls)


async def test_empty_goal_returns_not_ok():
    client = FakeClient(plan=_plan("fast"))
    wf = DynamicWorkflow(client)
    result = await wf.run("   ")
    assert result.ok is False
    assert result.plan == []
    assert client.calls == []  # never touched the model


# ── VERIFICATION + REPAIR ────────────────────────────────────────────────────


async def test_verifier_approves_clean_result():
    client = FakeClient(plan=_plan("research"), verifier={"ok": True, "critique": ""})
    wf = DynamicWorkflow(client, verify=True)
    result = await wf.run("do")

    r = result.results[0]
    assert r.verified is True
    assert r.repaired is False
    assert r.output == "output for workflow.t1"


async def test_verifier_flags_and_repairs():
    client = FakeClient(
        plan=_plan("code"),
        verifier={"ok": False, "critique": "the function has an off-by-one bug"},
    )
    wf = DynamicWorkflow(client, verify=True)
    result = await wf.run("write code")

    r = result.results[0]
    assert r.repaired is True
    assert r.verified is True
    assert r.output == "REPAIRED OUTPUT"
    assert r.critique == "the function has an off-by-one bug"
    assert any(c["agent"] == "workflow.repair.t1" for c in client.calls)


async def test_concurrency_cap_is_respected():
    # 5 subtasks, cap of 2 → engine must not raise and must complete all.
    client = FakeClient(plan=_plan("fast", "fast", "fast", "fast", "fast"))
    wf = DynamicWorkflow(client, max_concurrency=2, verify=False)
    result = await wf.run("spread")
    assert len(result.results) == 5
    assert all(r.ok for r in result.results)


async def test_subtask_model_defaults_to_strategy():
    t = SubTask(id="t1", title="x", prompt="p", kind=TaskKind.RESEARCH)
    assert t.model() == AIModel.STRATEGY


# ── STREAMING (run_events) ────────────────────────────────────────────────────


async def test_run_events_streams_all_phases():
    client = FakeClient(plan=_plan("research", "research"))
    wf = DynamicWorkflow(client, verify=False)
    events = [ev async for ev in wf.run_events("do a thing")]

    types = [e["type"] for e in events]
    assert types[0] == "start"
    assert types[1] == "plan"
    assert types.count("subtask_done") == 2
    assert types[-1] == "done"

    assert len(events[1]["subtasks"]) == 2
    assert all("id" in s and "title" in s and "kind" in s for s in events[1]["subtasks"])

    done = events[-1]
    assert done["ok"] is True
    assert done["synthesis"] == "FINAL SYNTHESIS"
    assert len(done["subtasks"]) == 2
    assert done["total_tokens"] > 0


async def test_run_events_empty_goal_emits_single_done():
    client = FakeClient(plan=_plan("fast"))
    wf = DynamicWorkflow(client)
    events = [ev async for ev in wf.run_events("   ")]
    assert events == [
        {"type": "done", "ok": False, "synthesis": "", "subtasks": [], "total_tokens": 0}
    ]
    assert client.calls == []  # never touched the model


async def test_run_events_verify_marks_subtasks():
    client = FakeClient(plan=_plan("code"), verifier={"ok": False, "critique": "bug"})
    wf = DynamicWorkflow(client, verify=True)
    events = [ev async for ev in wf.run_events("write code")]
    done = [e for e in events if e["type"] == "subtask_done"]
    assert len(done) == 1
    assert done[0]["result"]["repaired"] is True
    assert done[0]["result"]["output"] == "REPAIRED OUTPUT"


# ── CLARIFY-BEFORE-EXECUTE GATE ───────────────────────────────────────────────


async def test_clarify_gate_asks_instead_of_guessing():
    # Under-specified goal → ARIA asks, runs NO subagents (no guessed deliverable).
    client = FakeClient(
        plan=_plan("reason", "creative"),
        clarifier={
            "ready": False,
            "questions": ["What does your SaaS do?", "Who is it for?"],
            "intro": "Quick — a couple things first:",
        },
    )
    wf = DynamicWorkflow(client)
    result = await wf.run("make me 3 prices for my SaaS")

    assert result.ok is True
    assert result.results == []  # no subagents ran
    assert "Quick — a couple things first:" in result.synthesis
    assert "What does your SaaS do?" in result.synthesis
    assert "Who is it for?" in result.synthesis
    # The planner and subagents were never called.
    assert not any(c["agent"] == "workflow.planner" for c in client.calls)


async def test_clarify_gate_proceeds_when_ready():
    client = FakeClient(plan=_plan("research", "research"), clarifier={"ready": True})
    result = await DynamicWorkflow(client).run("Compare X and Y with these specifics ...")
    assert result.synthesis == "FINAL SYNTHESIS"
    assert len(result.results) == 2  # executed normally


async def test_clarify_can_be_disabled():
    client = FakeClient(
        plan=_plan("reason"), clarifier={"ready": False, "questions": ["ignored?"]}
    )
    # clarify=False → skips the gate and executes even a vague goal.
    result = await DynamicWorkflow(client, clarify=False).run("vague goal")
    assert len(result.results) == 1
    assert not any(c["agent"] == "workflow.clarify" for c in client.calls)


async def test_run_events_clarify_emits_single_done():
    client = FakeClient(
        plan=_plan("reason"),
        clarifier={"ready": False, "questions": ["What's the goal?"], "intro": "One sec:"},
    )
    wf = DynamicWorkflow(client)
    events = [ev async for ev in wf.run_events("do something big")]
    types = [e["type"] for e in events]
    assert "plan" not in types  # never planned
    assert types[-1] == "done"
    done = events[-1]
    assert done["subtasks"] == []
    assert "What's the goal?" in done["synthesis"]
