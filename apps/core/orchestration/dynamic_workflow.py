"""
dynamic_workflow.py — ARIA's Dynamic Workflow Engine.

This is the pattern that defines frontier 2026 AI (Claude Code Dynamic
Workflows, GPT Multi-agent, Gemini Antigravity): instead of responding with a
single model call, ARIA **decomposes** a goal into subtasks, launches
**subagents in parallel** routing each one to the optimal model, **verifies
adversarially** each result before accepting it, and integrates everything
into a coherent final response.

Phases:
    1. PLAN       — a strategist model decomposes the goal into 2-6
                    independent subtasks (JSON). On failure, degrades to a
                    single task.
    2. EXECUTE    — subagents run in parallel (with a concurrency cap, like
                    Claude Code's limit of 16) routed by task type.
    3. VERIFY     — each result is submitted to an adversarial verifier; if a
                    flaw is detected, a single repair attempt is made.
    4. SYNTHESIZE — an integrator model combines the verified outputs into
                    the final deliverable.

The engine depends only on `AriaAIClient`'s `.complete(...)` interface, which
makes it 100% testable without network access by injecting a fake client.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Protocol

from apps.core.tools.ai_client import AIModel, AIResponse

logger = logging.getLogger("aria.dynamic_workflow")

# Cap on concurrent subagents. The server is small; 6 keeps latency bounded
# without saturating the inference providers.
DEFAULT_CONCURRENCY = 6
# Hard cap on subtasks so a runaway plan doesn't blow up the cost.
MAX_SUBTASKS = 6


class TaskKind(StrEnum):
    """Subtask type → determines which model tier it gets routed to."""

    REASON = "reason"  # deep analysis, strategy
    CODE = "code"  # code generation / review
    RESEARCH = "research"  # information synthesis
    CREATIVE = "creative"  # copy, ideas, content
    FAST = "fast"  # simple, high-volume tasks


# Map of task type → model tier for the multi-provider router.
_KIND_TO_MODEL: dict[TaskKind, AIModel] = {
    TaskKind.REASON: AIModel.REASONING,
    TaskKind.CODE: AIModel.CODE,
    TaskKind.RESEARCH: AIModel.STRATEGY,
    TaskKind.CREATIVE: AIModel.CREATIVE,
    TaskKind.FAST: AIModel.FAST,
}


class SupportsComplete(Protocol):
    """Minimal interface the engine needs from the AI client."""

    async def complete(
        self,
        system: str,
        user: str,
        model: AIModel = ...,
        max_tokens: int = ...,
        temperature: float = ...,
        json_mode: bool = ...,
        agent_name: str = ...,
    ) -> AIResponse: ...


@dataclass
class SubTask:
    """A unit of work executed by a subagent."""

    id: str
    title: str
    prompt: str
    kind: TaskKind = TaskKind.RESEARCH

    def model(self) -> AIModel:
        return _KIND_TO_MODEL.get(self.kind, AIModel.STRATEGY)


@dataclass
class SubTaskResult:
    """Result of a subagent, with its verification trace."""

    task: SubTask
    output: str
    model_used: str
    tokens: int = 0
    latency_ms: int = 0
    ok: bool = True
    error: str | None = None
    verified: bool = False
    critique: str | None = None
    repaired: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.task.id,
            "title": self.task.title,
            "kind": self.task.kind.value,
            "model_used": self.model_used,
            "tokens": self.tokens,
            "latency_ms": self.latency_ms,
            "ok": self.ok,
            "verified": self.verified,
            "repaired": self.repaired,
            "critique": self.critique,
            "error": self.error,
            "output": self.output,
        }


@dataclass
class WorkflowResult:
    """Complete output of a dynamic workflow."""

    goal: str
    plan: list[SubTask]
    results: list[SubTaskResult]
    synthesis: str
    ok: bool = True
    total_tokens: int = 0
    duration_ms: int = 0
    started_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "goal": self.goal,
            "ok": self.ok,
            "synthesis": self.synthesis,
            "subtasks": [r.to_dict() for r in self.results],
            "plan_size": len(self.plan),
            "total_tokens": self.total_tokens,
            "duration_ms": self.duration_ms,
            "started_at": self.started_at,
        }


# ── PROMPTS ───────────────────────────────────────────────────────────────


def _detect_lang(text: str) -> str:
    """Best-effort 'en'/'es' from the goal, so we can FORCE the output language
    instead of hoping the model follows a soft instruction (ARIA's whole prompt
    scaffold is Spanish, which otherwise drags English goals into Spanish)."""
    t = (text or "").lower()
    es = len(re.findall(r"[ñáéíóú¿¡]", t)) + len(
        re.findall(
            r"\b(el|la|los|las|un|una|para|con|que|de|del|y|escribe|dame|hazme|"
            r"contenido|semana|publicaci[oó]n|posts?|imagen)\b",
            t,
        )
    )
    en = len(
        re.findall(
            r"\b(the|a|an|and|your|you|with|that|this|for|write|give|make|me|"
            r"content|week|research|posts?|image)\b",
            t,
        )
    )
    return "es" if es > en else "en"


def _lang_directive(lang: str) -> str:
    return (
        "IMPORTANT: Write your ENTIRE response in English, no matter what language "
        "these instructions are in. "
        if lang == "en"
        else "IMPORTANTE: Escribe TODA tu respuesta en español. "
    )


_PLANNER_SYSTEM = (
    "You are ARIA's planner, an autonomous agent system. You decompose a "
    "goal into INDEPENDENT subtasks that can run in parallel (none depending on another's "
    "result). Fewer well-defined subtasks is better than many trivial ones. Each subtask "
    "declares its type: 'reason' (analysis/strategy), "
    "'code' (programming), 'research' (information synthesis), 'creative' (copy/ideas) "
    "or 'fast' (simple tasks)."
)

_PLANNER_USER = """Goal:
{goal}
{context}
Return between 2 and {max_tasks} parallel subtasks as JSON with this exact shape:
{{"subtasks": [{{"title": "...", "prompt": "complete, self-contained instruction for the subagent", "kind": "reason|code|research|creative|fast"}}]}}
Each 'prompt' must be self-sufficient: the subagent does NOT see the overall goal or the other subtasks.
Write each 'title' and 'prompt' IN THE SAME LANGUAGE as the user's goal (if the goal is in English, in English; if it's in Spanish, in Spanish). Each 'prompt' must ask for the finished final DELIVERABLE (the actual, ready-to-use text/copy), not a summary or a plan of what would be done."""

_VERIFIER_SYSTEM = (
    "You are an adversarial verifier. Your job is to find real flaws in a "
    "subagent's result: incorrect claims, ignored requirements, code "
    "that wouldn't work, hallucinations. Be strict but fair. If the result "
    "reasonably fulfills the task, approve it."
)

_VERIFIER_USER = """Assigned task:
{prompt}

Subagent's result:
{output}

Does the result fulfill the task without serious flaws? Respond ONLY with JSON:
{{"ok": true|false, "critique": "if ok=false, explain the concrete flaw in one sentence; if ok=true, leave empty"}}"""

_SYNTH_SYSTEM = (
    "You are ARIA integrating your team's work into the FINAL DELIVERABLE for the user. "
    "You speak like a real person: warm, direct, opinionated — not like a corporate report. "
    "No 'As an AI', no empty jargon, no filler. "
    "KEY RULE: deliver the FINISHED work, ready to use, not a description of what "
    "you would do. If they ask for 5 posts, write the 5 COMPLETE posts word for word (with their hook and "
    "final copy), not 'we'll share how…'. If they ask for an article, write the article. The user "
    "must be able to copy and publish without rewriting anything. "
    "No generic titles or AI cliché phrases: specific hooks and copy, with real judgment. "
    "ALWAYS respond in the SAME language as the user's goal (if the goal is in English, "
    "respond in English; if it's in Spanish, in Spanish)."
)

_SYNTH_USER = """User's goal:
{goal}

Your team's work (subagents):
{parts}

Deliver the FINAL result ready to use — the complete text, not a summary or a plan of what
you would do. Write it in the language of the goal. If something depended on data we didn't have, make a
reasonable assumption and continue; only at the very end, in one line, you may offer to refine it."""

_CLARIFY_SYSTEM = (
    "You are ARIA deciding whether to EXECUTE right away or — only in clear cases — whether a "
    "piece of information is missing without which the deliverable would come out useless or in the "
    "wrong direction. Your default bias is to EXECUTE and "
    "deliver something strong the person can review; asking is the exception, not the rule. "
    "You speak like a person — warm and direct."
)

_CLARIFY_USER = """User's request:
{goal}
{context}
By default EXECUTE (ready=true) and deliver a strong first result with reasonable assumptions; it can be refined afterward.
Only set ready=false if, WITHOUT a piece of information, the deliverable would be genuinely useless or go in the wrong direction — the typical case is being asked for pricing/tiers without knowing what the product is, for whom, or its value metric.
For creative or content tasks (posts, images, articles, scripts, research) with a clear topic → ALWAYS ready=true: produce an excellent first draft and offer to refine it afterward. Don't interrogate the user at the moment they want to see the work.
Respond ONLY with JSON:
{{"ready": true|false, "questions": ["short, concrete question 1", "..."], "intro": "one warm, human sentence to accompany the questions; empty if ready=true"}}
Respond in the language of the request."""


class DynamicWorkflow:
    """Orchestrator for multi-agent dynamic workflows.

    Usage:
        wf = DynamicWorkflow(client)
        result = await wf.run("Design and validate a launch plan for X")
        print(result.synthesis)
    """

    def __init__(
        self,
        client: SupportsComplete,
        max_concurrency: int = DEFAULT_CONCURRENCY,
        verify: bool = True,
        clarify: bool = True,
    ) -> None:
        self._client = client
        self._sem = asyncio.Semaphore(max(1, max_concurrency))
        self._verify = verify
        # When True, an under-specified goal yields clarifying questions instead
        # of a guessed deliverable (no subagents run). The chat shows them as a turn.
        self._clarify = clarify
        # Token counters for the phases that don't live in a SubTaskResult
        # (planner + synthesizer). Reset at the start of each run().
        self._plan_tokens = 0
        self._synth_tokens = 0
        self._out_lang = "en"  # set per-run from the goal in run()/run_events()

    # ── MAIN ORCHESTRATION ────────────────────────────────────────────────

    async def run(self, goal: str, context: str | None = None) -> WorkflowResult:
        """Runs the full flow: plan → parallel → verify → synthesize."""
        t0 = time.time()
        goal = (goal or "").strip()
        if not goal:
            return WorkflowResult(
                goal=goal, plan=[], results=[], synthesis="", ok=False, duration_ms=0
            )

        self._plan_tokens = 0
        self._synth_tokens = 0
        self._out_lang = _detect_lang(goal)

        # Clarify before executing: if key context is missing, ask instead of guessing.
        if self._clarify:
            clarify_msg = await self._assess(goal, context)
            if clarify_msg:
                return WorkflowResult(
                    goal=goal,
                    plan=[],
                    results=[],
                    synthesis=clarify_msg,
                    ok=True,
                    total_tokens=self._plan_tokens,
                    duration_ms=int((time.time() - t0) * 1000),
                )

        plan = await self._plan(goal, context)
        logger.info("[workflow] plan of %d subtasks for: %s", len(plan), goal[:80])

        # Run subagents in parallel (with a concurrency cap).
        results = await asyncio.gather(*(self._execute(task) for task in plan))

        # Verify (and repair once) adversarially, also in parallel.
        if self._verify:
            results = list(await asyncio.gather(*(self._verify_and_repair(r) for r in results)))

        synthesis = await self._synthesize(goal, results)

        # Real cost = subagents (incl. verify + repair) + planner + synth.
        total_tokens = sum(r.tokens for r in results) + self._plan_tokens + self._synth_tokens
        ok = any(r.ok for r in results) and bool(synthesis)
        return WorkflowResult(
            goal=goal,
            plan=plan,
            results=results,
            synthesis=synthesis,
            ok=ok,
            total_tokens=total_tokens,
            duration_ms=int((time.time() - t0) * 1000),
        )

    # ── STREAMING ─────────────────────────────────────────────────────────

    async def run_events(self, goal: str, context: str | None = None):
        """Same as run(), but emits events as it progresses — for SSE.

        Yields dicts with `type`:
            start        — {goal}
            plan         — {subtasks:[{id,title,kind}]}
            subtask_done — {result:{...}}   (one per subagent, on complete+verify)
            done         — {ok, synthesis, subtasks:[...], total_tokens, duration_ms}
            error        — {error}          (only if something unrecoverable happens)

        Subagents complete via as_completed → the client sees each one
        appear as soon as it finishes, instead of waiting for the whole batch.
        """
        t0 = time.time()
        goal = (goal or "").strip()
        if not goal:
            yield {"type": "done", "ok": False, "synthesis": "", "subtasks": [], "total_tokens": 0}
            return

        self._plan_tokens = 0
        self._synth_tokens = 0
        self._out_lang = _detect_lang(goal)

        try:
            yield {"type": "start", "goal": goal}

            # Clarify before executing: if context is missing, ask (without running subagents).
            if self._clarify:
                clarify_msg = await self._assess(goal, context)
                if clarify_msg:
                    yield {
                        "type": "done",
                        "ok": True,
                        "synthesis": clarify_msg,
                        "subtasks": [],
                        "total_tokens": self._plan_tokens,
                        "duration_ms": int((time.time() - t0) * 1000),
                    }
                    return

            plan = await self._plan(goal, context)
            yield {
                "type": "plan",
                "subtasks": [{"id": t.id, "title": t.title, "kind": t.kind.value} for t in plan],
            }

            async def _one(task: SubTask) -> SubTaskResult:
                res = await self._execute(task)
                if self._verify:
                    res = await self._verify_and_repair(res)
                return res

            results: list[SubTaskResult] = []
            for fut in asyncio.as_completed([_one(t) for t in plan]):
                res = await fut
                results.append(res)
                yield {"type": "subtask_done", "result": res.to_dict()}

            synthesis = await self._synthesize(goal, results)
            total = sum(r.tokens for r in results) + self._plan_tokens + self._synth_tokens
            yield {
                "type": "done",
                "ok": any(r.ok for r in results) and bool(synthesis),
                "synthesis": synthesis,
                "subtasks": [r.to_dict() for r in results],
                "total_tokens": total,
                "duration_ms": int((time.time() - t0) * 1000),
            }
        except Exception as exc:  # noqa: BLE001 — the stream must never hang without closing.
            logger.warning("[workflow] run_events failed: %s", exc)
            yield {"type": "error", "error": str(exc)[:200]}

    # ── PHASE 0: CLARIFY ──────────────────────────────────────────────────

    async def _assess(self, goal: str, context: str | None) -> str | None:
        """Returns a clarifying message (warm, with 1-3 questions) if the goal
        is missing key context; None if there's already enough to execute.

        Best-effort: on any failure, or if the model says it's ready, returns
        None so as not to block a well-specified request.
        """
        ctx = f"\nAdditional context:\n{context}\n" if context else "\n"
        try:
            resp = await self._client.complete(
                system=_CLARIFY_SYSTEM,
                user=_CLARIFY_USER.format(goal=goal, context=ctx),
                model=AIModel.FAST,
                max_tokens=400,
                temperature=0.2,
                json_mode=True,
                agent_name="workflow.clarify",
            )
            if not resp or not resp.success:
                return None
            self._plan_tokens += resp.tokens_used
            data = json.loads(resp.content)
            if data.get("ready", True):
                return None
            questions = [str(q).strip() for q in (data.get("questions") or []) if str(q).strip()][
                :3
            ]
            if not questions:
                return None
            intro = (
                str(data.get("intro") or "").strip()
                or "Before we start, tell me a couple of things so this comes out right:"
            )
            return intro + "\n\n" + "\n".join("- " + q for q in questions)
        except Exception:  # noqa: BLE001 — clarifying is best-effort; when in doubt, execute.
            return None

    # ── PHASE 1: PLAN ─────────────────────────────────────────────────────

    async def _plan(self, goal: str, context: str | None) -> list[SubTask]:
        ctx = f"\nAdditional context:\n{context}\n" if context else "\n"
        try:
            resp = await self._client.complete(
                system=_PLANNER_SYSTEM,
                user=_PLANNER_USER.format(goal=goal, context=ctx, max_tasks=MAX_SUBTASKS),
                model=AIModel.STRATEGY,
                max_tokens=1200,
                temperature=0.3,
                json_mode=True,
                agent_name="workflow.planner",
            )
            if resp and resp.success:
                self._plan_tokens += resp.tokens_used
            data = json.loads(resp.content) if resp and resp.success else {}
            raw = data.get("subtasks") or []
            tasks: list[SubTask] = []
            for i, item in enumerate(raw[:MAX_SUBTASKS]):
                if not isinstance(item, dict):
                    continue
                prompt = str(item.get("prompt") or item.get("title") or "").strip()
                if not prompt:
                    continue
                kind = self._coerce_kind(item.get("kind"))
                tasks.append(
                    SubTask(
                        id=f"t{i + 1}",
                        title=str(item.get("title") or f"Subtask {i + 1}").strip()[:120],
                        prompt=prompt,
                        kind=kind,
                    )
                )
            if tasks:
                return tasks
        except Exception as exc:  # noqa: BLE001 — the planner must never take down the flow.
            logger.warning("[workflow] planning failed (%s) — degrading to a single task", exc)

        # Degradation: a single subtask that is the goal as-is.
        return [SubTask(id="t1", title="Full objective", prompt=goal, kind=TaskKind.REASON)]

    @staticmethod
    def _coerce_kind(value: Any) -> TaskKind:
        try:
            return TaskKind(str(value).strip().lower())
        except ValueError:
            return TaskKind.RESEARCH

    # ── PHASE 2: EXECUTE SUBAGENT ─────────────────────────────────────────

    async def _execute(self, task: SubTask) -> SubTaskResult:
        system = _lang_directive(self._out_lang) + (
            "You are a specialized ARIA subagent. You execute ONE concrete task with "
            "rigor and return the finished, ready-to-use DELIVERABLE (the actual text/copy, "
            "not a description or a plan), with no preamble or apologies."
        )
        async with self._sem:
            try:
                resp = await self._client.complete(
                    system=system,
                    user=task.prompt,
                    model=task.model(),
                    max_tokens=1800,
                    temperature=0.6,
                    agent_name=f"workflow.{task.id}",
                )
                if resp and resp.success:
                    return SubTaskResult(
                        task=task,
                        output=(resp.content or "").strip(),
                        model_used=resp.model,
                        tokens=resp.tokens_used,
                        latency_ms=resp.latency_ms,
                        ok=True,
                    )
                return SubTaskResult(
                    task=task,
                    output="",
                    model_used=resp.model if resp else "none",
                    ok=False,
                    error=(resp.error if resp else "no response"),
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("[workflow] subagent %s failed: %s", task.id, exc)
                return SubTaskResult(
                    task=task, output="", model_used="none", ok=False, error=str(exc)[:200]
                )

    # ── PHASE 3: VERIFY + REPAIR ──────────────────────────────────────────

    async def _verify_and_repair(self, result: SubTaskResult) -> SubTaskResult:
        if not result.ok or not result.output:
            return result
        verdict = await self._verify_one(result)
        if verdict is None:
            # The verifier isn't available: don't block, accept as-is.
            result.verified = True
            return result
        ok, critique = verdict
        if ok:
            result.verified = True
            return result

        # A single repair attempt guided by the critique.
        result.critique = critique
        repaired = await self._repair(result, critique)
        if repaired is not None:
            result.output = repaired.output
            result.tokens += repaired.tokens
            result.latency_ms += repaired.latency_ms
            result.model_used = repaired.model_used
            result.repaired = True
            result.verified = True
        return result

    async def _verify_one(self, result: SubTaskResult) -> tuple[bool, str] | None:
        async with self._sem:
            try:
                resp = await self._client.complete(
                    system=_VERIFIER_SYSTEM,
                    user=_VERIFIER_USER.format(
                        prompt=result.task.prompt, output=result.output[:4000]
                    ),
                    model=AIModel.FAST,
                    max_tokens=300,
                    temperature=0.0,
                    json_mode=True,
                    agent_name=f"workflow.verify.{result.task.id}",
                )
                if not resp or not resp.success:
                    return None
                result.tokens += resp.tokens_used
                data = json.loads(resp.content)
                return bool(data.get("ok", True)), str(data.get("critique") or "").strip()
            except Exception:  # noqa: BLE001 — verification is best-effort.
                return None

    async def _repair(self, result: SubTaskResult, critique: str) -> SubTaskResult | None:
        async with self._sem:
            try:
                resp = await self._client.complete(
                    system=(
                        "You are an ARIA subagent fixing your own work. A reviewer "
                        "found a flaw. Return the complete CORRECTED result, not an "
                        "explanation of the change."
                    ),
                    user=(
                        f"Task:\n{result.task.prompt}\n\n"
                        f"Your previous result:\n{result.output[:3000]}\n\n"
                        f"Flaw found by the reviewer:\n{critique}\n\n"
                        "Deliver the corrected result:"
                    ),
                    model=result.task.model(),
                    max_tokens=1800,
                    temperature=0.4,
                    agent_name=f"workflow.repair.{result.task.id}",
                )
                if resp and resp.success and resp.content.strip():
                    return SubTaskResult(
                        task=result.task,
                        output=resp.content.strip(),
                        model_used=resp.model,
                        tokens=resp.tokens_used,
                        latency_ms=resp.latency_ms,
                    )
            except Exception:  # noqa: BLE001
                return None
        return None

    # ── PHASE 4: SYNTHESIZE ───────────────────────────────────────────────

    async def _synthesize(self, goal: str, results: list[SubTaskResult]) -> str:
        usable = [r for r in results if r.ok and r.output]
        if not usable:
            return ""
        # Shortcut: with a single result there's nothing to integrate.
        if len(usable) == 1:
            return usable[0].output

        parts = "\n\n".join(f"### {r.task.title}\n{r.output[:2500]}" for r in usable)
        try:
            resp = await self._client.complete(
                system=_lang_directive(self._out_lang) + _SYNTH_SYSTEM,
                user=_SYNTH_USER.format(goal=goal, parts=parts),
                model=AIModel.STRATEGY,
                max_tokens=2200,
                temperature=0.5,
                agent_name="workflow.synth",
            )
            if resp and resp.success and resp.content.strip():
                self._synth_tokens += resp.tokens_used
                return resp.content.strip()
        except Exception as exc:  # noqa: BLE001
            logger.warning("[workflow] synthesis failed: %s", exc)

        # Degradation: concatenate the verified sections.
        return "\n\n".join(f"**{r.task.title}**\n{r.output}" for r in usable)


# ── FACTORY ──────────────────────────────────────────────────────────────


async def get_dynamic_workflow(
    max_concurrency: int = DEFAULT_CONCURRENCY, verify: bool = True
) -> DynamicWorkflow:
    """Builds a dynamic workflow using ARIA's shared AI client."""
    from apps.core.tools.ai_client import get_ai_client_async

    client = await get_ai_client_async()
    return DynamicWorkflow(client, max_concurrency=max_concurrency, verify=verify)
