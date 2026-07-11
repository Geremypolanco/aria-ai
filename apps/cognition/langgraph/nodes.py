"""
ARIA LangGraph — Node functions for the cognitive StateGraph.

Each node takes AgentState and returns a partial update dict.
AI calls use get_ai_client() (SYNC) then await ai.complete(...) inside
a thread-pool helper to handle the async-inside-sync constraint of
LangGraph's synchronous node dispatch.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging
from typing import TYPE_CHECKING, Any

from apps.core.tools.ai_client import get_ai_client

if TYPE_CHECKING:
    from apps.cognition.langgraph.agent_state import AgentState

logger = logging.getLogger("aria.cognition.nodes")


# ── async-inside-sync helper ──────────────────────────────────────────────────


def _run_async(coro) -> Any:
    """
    Run an async coroutine from a synchronous context.

    If an event loop is already running (LangGraph's invocation context),
    we cannot block it — so we spin up a thread with its own fresh event loop
    via asyncio.run(). Otherwise we create a fresh loop with asyncio.run().

    We deliberately do NOT use asyncio.get_event_loop(): on Python 3.12+ it
    raises when no current loop is set (e.g. after a test framework tears one
    down), which would silently drop the coroutine. asyncio.get_running_loop()
    is the correct, side-effect-free way to detect a live loop.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        running = False
    else:
        running = True

    try:
        if running:
            # A loop is already running here → run the coroutine in a worker
            # thread that owns its own fresh loop.
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                return pool.submit(asyncio.run, coro).result(timeout=60)
        # No running loop → safe to create a fresh one and run to completion.
        return asyncio.run(coro)
    except Exception as exc:
        logger.warning("[_run_async] coroutine failed: %s", exc)
        return None


# ── node implementations ──────────────────────────────────────────────────────


def analyze_task(state: AgentState) -> dict:
    """
    Node: ANALYZE
    Reads the task and any existing context, produces initial reasoning steps.
    Returns: reasoning_steps update + status="planning"
    """
    task = state.get("task", "")
    context = state.get("context", {})
    iteration = state.get("iteration", 0)

    ai = get_ai_client()
    new_steps: list[str] = []

    if ai is not None:
        ctx_str = ""
        if context:
            ctx_items = [f"{k}: {v}" for k, v in list(context.items())[:5]]
            ctx_str = "\nContext:\n" + "\n".join(ctx_items)

        system = (
            "You are an analytical reasoning agent. "
            "Break down the task into key observations and sub-questions. "
            "Be concise and structured."
        )
        user = (
            f"Task: {task}{ctx_str}\n"
            f"Iteration: {iteration}\n"
            "List 2-3 key observations or sub-questions to address this task."
        )

        async def _call():
            return await ai.complete(
                system=system,
                user=user,
                max_tokens=400,
                agent_name="analyze_task",
            )

        response = _run_async(_call())
        if response and response.success and response.content:
            step = f"[Iteration {iteration}] Analysis: {response.content.strip()}"
            new_steps.append(step)
        else:
            new_steps.append(
                f"[Iteration {iteration}] Analysis: could not reach AI — proceeding with task as-is"
            )
    else:
        new_steps.append(f"[Iteration {iteration}] Analysis: AI client unavailable")

    return {
        "reasoning_steps": new_steps,
        "status": "planning",
    }


def create_plan(state: AgentState) -> dict:
    """
    Node: PLAN
    Uses reasoning steps to produce an ordered execution plan.
    Returns: plan list + status="executing"
    """
    task = state.get("task", "")
    reasoning_steps = state.get("reasoning_steps", [])
    analysis_summary = reasoning_steps[-1] if reasoning_steps else ""

    ai = get_ai_client()
    plan: list[str] = []

    if ai is not None:
        system = (
            "You are a planning agent. Given a task and initial analysis, "
            "create a concrete step-by-step plan. "
            "Return exactly 3-5 numbered steps, one per line."
        )
        user = (
            f"Task: {task}\n" f"Analysis: {analysis_summary}\n" "Create a numbered execution plan:"
        )

        async def _call():
            return await ai.complete(
                system=system,
                user=user,
                max_tokens=400,
                agent_name="create_plan",
            )

        response = _run_async(_call())
        if response and response.success and response.content:
            lines = [line.strip() for line in response.content.strip().splitlines() if line.strip()]
            plan = lines[:5] if lines else [f"Execute: {task}"]
        else:
            plan = [f"Execute task directly: {task}"]
    else:
        plan = [f"Fallback step: {task}"]

    return {
        "plan": plan,
        "status": "executing",
    }


def execute_step(state: AgentState) -> dict:
    """
    Node: EXECUTE
    Executes the current plan step using AI.
    Returns: current_step increment + result + status="reflecting"
    """
    task = state.get("task", "")
    plan = state.get("plan", [])
    current_step = state.get("current_step", 0)
    context = state.get("context", {})

    step_desc = plan[current_step] if current_step < len(plan) else f"Complete task: {task}"
    ai = get_ai_client()
    result = ""

    if ai is not None:
        system = (
            "You are an execution agent. Carry out the given step and produce "
            "a concrete, useful output or result. Be specific and actionable."
        )
        ctx_str = ""
        if context:
            ctx_items = [f"{k}: {v}" for k, v in list(context.items())[:5]]
            ctx_str = "\nContext:\n" + "\n".join(ctx_items)

        user = (
            f"Overall task: {task}{ctx_str}\n"
            f"Current step to execute: {step_desc}\n"
            "Provide the result or output for this step."
        )

        async def _call():
            return await ai.complete(
                system=system,
                user=user,
                max_tokens=600,
                agent_name="execute_step",
            )

        response = _run_async(_call())
        if response and response.success and response.content:
            result = response.content.strip()
        else:
            result = f"Step '{step_desc}' executed (no AI response)"
    else:
        result = f"Step '{step_desc}' executed without AI"

    return {
        "current_step": current_step + 1,
        "result": result,
        "status": "reflecting",
    }


def reflect(state: AgentState) -> dict:
    """
    Node: REFLECT
    Evaluates the result, assigns confidence, decides whether to loop or finish.
    Returns: confidence + iteration + status ("done" | "thinking" | "failed")
    """
    task = state.get("task", "")
    result = state.get("result", "")
    iteration = state.get("iteration", 0)
    max_iterations = state.get("max_iterations", 3)
    plan = state.get("plan", [])
    current_step = state.get("current_step", 0)

    # Hard cap: stop if we've hit max iterations
    new_iteration = iteration + 1
    if new_iteration >= max_iterations:
        confidence = 0.65  # partial confidence — we ran out of cycles
        return {
            "confidence": confidence,
            "iteration": new_iteration,
            "status": "done",
        }

    # If there are more plan steps to execute, continue executing
    if current_step < len(plan):
        return {
            "confidence": 0.5,
            "iteration": new_iteration,
            "status": "executing",  # will route back through execute
        }

    ai = get_ai_client()
    confidence = 0.75
    status = "done"

    if ai is not None:
        system = (
            "You are a quality-assurance agent. "
            "Score how well the result answers the original task (0.0 to 1.0). "
            "Reply with ONLY a float between 0.0 and 1.0, nothing else."
        )
        user = f"Task: {task}\n" f"Result: {result}\n" "Confidence score (0.0–1.0):"

        async def _call():
            return await ai.complete(
                system=system,
                user=user,
                max_tokens=10,
                agent_name="reflect",
            )

        response = _run_async(_call())
        if response and response.success and response.content:
            try:
                raw = response.content.strip().split()[0]
                parsed = float(raw)
                confidence = max(0.0, min(1.0, parsed))
            except (ValueError, IndexError):
                confidence = 0.75

    # If confidence is low and we have iterations left, retry
    if confidence < 0.5 and new_iteration < max_iterations:
        status = "thinking"
    else:
        status = "done"

    return {
        "confidence": confidence,
        "iteration": new_iteration,
        "status": status,
    }


def handle_failure(state: AgentState) -> dict:
    """
    Node: FAILURE
    Handles terminal failure — records the failure state.
    Returns: status="failed" + result explaining the failure
    """
    task = state.get("task", "")
    iteration = state.get("iteration", 0)
    existing_result = state.get("result", "")

    failure_msg = (
        f"Task '{task}' could not be completed after {iteration} iteration(s). "
        f"Last result: {existing_result or '(none)'}"
    )
    logger.warning("[handle_failure] %s", failure_msg)

    return {
        "status": "failed",
        "result": failure_msg,
    }
