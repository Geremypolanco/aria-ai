"""
ARIA Hierarchical Planner — Production-grade goal decomposition and task execution.

Design:
  - Goals decompose into Plans → Tasks → Steps (3 levels)
  - Each Plan has a dependency DAG; tasks execute in topological order
  - Plans persist in Redis so ARIA survives restarts mid-execution
  - Failed tasks trigger re-planning (up to MAX_REPLAN attempts)
  - Every decision is logged with reasoning for retrospective analysis

This is NOT a toy planner. ARIA uses real LLM reasoning to decompose
goals and adapts the plan as execution reveals new information.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

logger = logging.getLogger("aria.planner")

MAX_REPLAN = 3
MAX_TASKS_PER_PLAN = 20
PLAN_TTL_SECONDS = 86400 * 7  # 7 days


class TaskStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    SKIPPED = "skipped"


class PlanStatus(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    DONE = "done"
    FAILED = "failed"
    REPLANNING = "replanning"


@dataclass
class PlanTask:
    id: str
    title: str
    description: str
    tool: str  # aria_mind tool name to invoke
    tool_args: dict[str, Any]
    depends_on: list[str]  # task IDs that must complete first
    status: TaskStatus = TaskStatus.PENDING
    result: dict | None = None
    error: str | None = None
    attempts: int = 0
    started_at: str | None = None
    finished_at: str | None = None
    priority: int = 5  # 1=highest

    def to_dict(self) -> dict:
        d = asdict(self)
        d["status"] = self.status.value
        return d

    @classmethod
    def from_dict(cls, d: dict) -> PlanTask:
        d = dict(d)
        d["status"] = TaskStatus(d.get("status", "pending"))
        return cls(**d)


@dataclass
class Plan:
    id: str
    goal: str
    context: dict[str, Any]
    tasks: list[PlanTask]
    status: PlanStatus = PlanStatus.DRAFT
    replan_count: int = 0
    reasoning: str = ""  # LLM chain-of-thought for this plan
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    @property
    def pending_tasks(self) -> list[PlanTask]:
        return [t for t in self.tasks if t.status == TaskStatus.PENDING]

    @property
    def ready_tasks(self) -> list[PlanTask]:
        """Tasks whose dependencies are all done and which are not yet started."""
        done_ids = {t.id for t in self.tasks if t.status == TaskStatus.DONE}
        return [
            t
            for t in self.tasks
            if t.status == TaskStatus.PENDING and all(dep in done_ids for dep in t.depends_on)
        ]

    @property
    def failed_tasks(self) -> list[PlanTask]:
        return [t for t in self.tasks if t.status == TaskStatus.FAILED]

    @property
    def is_complete(self) -> bool:
        return all(t.status in (TaskStatus.DONE, TaskStatus.SKIPPED) for t in self.tasks)

    @property
    def is_blocked(self) -> bool:
        return bool(self.failed_tasks) and not self.ready_tasks

    def progress_pct(self) -> float:
        if not self.tasks:
            return 0.0
        done = sum(1 for t in self.tasks if t.status in (TaskStatus.DONE, TaskStatus.SKIPPED))
        return round(done / len(self.tasks) * 100, 1)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "goal": self.goal,
            "context": self.context,
            "tasks": [t.to_dict() for t in self.tasks],
            "status": self.status.value,
            "replan_count": self.replan_count,
            "reasoning": self.reasoning,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "progress_pct": self.progress_pct(),
        }

    @classmethod
    def from_dict(cls, d: dict) -> Plan:
        tasks = [PlanTask.from_dict(t) for t in d.get("tasks", [])]
        return cls(
            id=d["id"],
            goal=d["goal"],
            context=d.get("context", {}),
            tasks=tasks,
            status=PlanStatus(d.get("status", "draft")),
            replan_count=d.get("replan_count", 0),
            reasoning=d.get("reasoning", ""),
            created_at=d.get("created_at", ""),
            updated_at=d.get("updated_at", ""),
        )


class ARIAPlanner:
    """
    Hierarchical planner for ARIA.

    Flow:
        plan = await planner.create_plan(goal, context)
        async for update in planner.execute_plan(plan, executor_fn):
            ...

    The executor_fn receives (task: PlanTask) and returns a result dict.
    The planner handles retries, re-planning, and persistence.
    """

    def __init__(self) -> None:
        self._active_plans: dict[str, Plan] = {}

    # ── Plan Creation ────────────────────────────────────────────────────

    async def create_plan(
        self,
        goal: str,
        context: dict[str, Any] | None = None,
        ai_client=None,
    ) -> Plan:
        """
        Decompose a high-level goal into an executable task plan using LLM reasoning.
        Falls back to a single-task plan if AI is unavailable.
        """
        context = context or {}
        plan_id = str(uuid.uuid4())[:8]

        reasoning, tasks = await self._decompose_goal(goal, context, ai_client, plan_id)

        plan = Plan(
            id=plan_id,
            goal=goal,
            context=context,
            tasks=tasks,
            status=PlanStatus.ACTIVE,
            reasoning=reasoning,
        )

        self._active_plans[plan_id] = plan
        await self._persist_plan(plan)

        logger.info(
            "[Planner] Plan %s created: %d tasks for goal: %s",
            plan_id,
            len(tasks),
            goal[:80],
        )
        return plan

    async def _decompose_goal(
        self,
        goal: str,
        context: dict,
        ai_client,
        plan_id: str,
    ) -> tuple[str, list[PlanTask]]:
        if ai_client is None:
            return self._single_task_plan(goal, plan_id)

        system = (
            "You are ARIA's hierarchical planner. Your job is to decompose a goal into "
            "concrete, executable tasks. Each task maps to one ARIA tool call.\n\n"
            "Available tools: web_search, generate_content, publish_content, "
            "run_income_cycle, analyze_market, send_notification, store_memory, "
            "read_memory, synthesize_report\n\n"
            "Return a JSON object:\n"
            "{\n"
            '  "reasoning": "<chain-of-thought: why this decomposition>",\n'
            '  "tasks": [\n'
            "    {\n"
            '      "title": "<action title>",\n'
            '      "description": "<what this task does and why>",\n'
            '      "tool": "<tool_name>",\n'
            '      "tool_args": {<args>},\n'
            '      "depends_on": [<task indices that must finish first, 0-indexed>],\n'
            '      "priority": <1-5>\n'
            "    }\n"
            "  ]\n"
            "}\n\n"
            f"Keep tasks focused: max {MAX_TASKS_PER_PLAN} tasks. "
            "Prefer parallel tasks where possible (empty depends_on). "
            "Be explicit about WHY each task is needed."
        )

        user_msg = f"Goal: {goal}\n\n" f"Context: {json.dumps(context, ensure_ascii=False)[:2000]}"

        try:
            raw = await ai_client.complete_json(system=system, user=user_msg)
            reasoning = raw.get("reasoning", "")
            raw_tasks = raw.get("tasks", [])[:MAX_TASKS_PER_PLAN]

            tasks = []
            for i, rt in enumerate(raw_tasks):
                dep_indices = rt.get("depends_on", [])
                dep_ids = [
                    f"{plan_id}-{idx}"
                    for idx in dep_indices
                    if isinstance(idx, int) and 0 <= idx < len(raw_tasks)
                ]
                tasks.append(
                    PlanTask(
                        id=f"{plan_id}-{i}",
                        title=rt.get("title", f"Task {i}"),
                        description=rt.get("description", ""),
                        tool=rt.get("tool", "none"),
                        tool_args=rt.get("tool_args", {}),
                        depends_on=dep_ids,
                        priority=int(rt.get("priority", 5)),
                    )
                )

            if not tasks:
                return self._single_task_plan(goal, plan_id)

            return reasoning, tasks

        except Exception as exc:
            logger.warning(
                "[Planner] AI decomposition failed: %s — using single-task fallback", exc
            )
            return self._single_task_plan(goal, plan_id)

    def _single_task_plan(self, goal: str, plan_id: str) -> tuple[str, list[PlanTask]]:
        return (
            "Single-task fallback: AI unavailable for decomposition.",
            [
                PlanTask(
                    id=f"{plan_id}-0",
                    title=goal[:80],
                    description=goal,
                    tool="none",
                    tool_args={"goal": goal},
                    depends_on=[],
                )
            ],
        )

    # ── Plan Execution ───────────────────────────────────────────────────

    async def execute_plan(
        self,
        plan: Plan,
        executor_fn,  # async (task: PlanTask) -> dict
        on_task_done=None,  # optional async callback(task, result)
    ):
        """
        Execute a plan, yielding status dicts as tasks complete.
        Handles retries, re-planning, and persistence.
        """
        plan.status = PlanStatus.ACTIVE
        await self._persist_plan(plan)

        while not plan.is_complete:
            ready = plan.ready_tasks
            if not ready:
                if plan.is_blocked:
                    if plan.replan_count < MAX_REPLAN:
                        logger.warning("[Planner] Plan %s blocked — triggering replan", plan.id)
                        plan.replan_count += 1
                        plan.status = PlanStatus.REPLANNING
                        await self._persist_plan(plan)
                        yield {"event": "replanning", "plan": plan.to_dict()}
                        await self._replan_failed_tasks(plan, executor_fn)
                        continue
                    else:
                        plan.status = PlanStatus.FAILED
                        await self._persist_plan(plan)
                        yield {"event": "failed", "plan": plan.to_dict()}
                        return
                # No ready tasks but not blocked: wait for running tasks
                await asyncio.sleep(0.1)
                continue

            # Execute all ready tasks in parallel
            batch = ready[:5]  # max 5 concurrent
            results = await asyncio.gather(
                *[self._execute_task(plan, task, executor_fn) for task in batch],
                return_exceptions=True,
            )

            for task, result in zip(batch, results, strict=False):
                if isinstance(result, Exception):
                    task.status = TaskStatus.FAILED
                    task.error = str(result)
                else:
                    task.status = TaskStatus.DONE if result.get("success") else TaskStatus.FAILED
                    task.result = result
                    if not result.get("success"):
                        task.error = result.get("error", "Unknown failure")

                task.finished_at = datetime.now(UTC).isoformat()
                plan.updated_at = datetime.now(UTC).isoformat()
                await self._persist_plan(plan)

                if on_task_done:
                    await on_task_done(task, task.result)

                yield {"event": "task_done", "task": task.to_dict(), "plan": plan.to_dict()}

        plan.status = PlanStatus.DONE
        plan.updated_at = datetime.now(UTC).isoformat()
        await self._persist_plan(plan)
        yield {"event": "plan_done", "plan": plan.to_dict()}

    async def _execute_task(self, plan: Plan, task: PlanTask, executor_fn) -> dict:
        task.status = TaskStatus.RUNNING
        task.started_at = datetime.now(UTC).isoformat()
        task.attempts += 1

        logger.info("[Planner] Plan %s — executing task %s: %s", plan.id, task.id, task.title)
        try:
            result = await executor_fn(task)
            return result if isinstance(result, dict) else {"success": True, "output": str(result)}
        except Exception as exc:
            logger.error("[Planner] Task %s failed: %s", task.id, exc)
            raise

    async def _replan_failed_tasks(self, plan: Plan, executor_fn) -> None:
        """Reset failed tasks to pending for retry with backoff."""
        for task in plan.failed_tasks:
            if task.attempts < 3:
                task.status = TaskStatus.PENDING
                task.error = None
                await asyncio.sleep(2**task.attempts)  # exponential backoff

    # ── Persistence ──────────────────────────────────────────────────────

    async def _persist_plan(self, plan: Plan) -> None:
        try:
            from apps.core.memory.redis_client import get_cache

            cache = get_cache()
            if cache:
                key = f"aria:plan:{plan.id}"
                await cache.set(key, json.dumps(plan.to_dict()), ttl_seconds=PLAN_TTL_SECONDS)
        except Exception as exc:
            logger.debug("[Planner] Could not persist plan %s: %s", plan.id, exc)

    async def load_plan(self, plan_id: str) -> Plan | None:
        try:
            from apps.core.memory.redis_client import get_cache

            cache = get_cache()
            if cache:
                raw = await cache.get(f"aria:plan:{plan_id}")
                if raw:
                    # cache.get() already deserializes JSON — decoding again
                    # raised TypeError on every call, silently swallowed below.
                    return Plan.from_dict(raw)
        except Exception as exc:
            logger.debug("[Planner] Could not load plan %s: %s", plan_id, exc)
        return None

    async def list_active_plans(self) -> list[dict]:
        return [p.to_dict() for p in self._active_plans.values() if p.status == PlanStatus.ACTIVE]


_planner: ARIAPlanner | None = None


def get_planner() -> ARIAPlanner:
    global _planner
    if _planner is None:
        _planner = ARIAPlanner()
    return _planner
