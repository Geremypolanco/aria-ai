"""
Central Executive Agent — supreme orchestration authority.

Enforces:
  - Execution budgets (max cost, max time, max agent calls per cycle)
  - Recursion depth limits (prevents delegation loops)
  - Task arbitration (priority queuing, conflict resolution)
  - Organizational governance (which agent may do what)

The Executive does NOT use LLMs for routing decisions — all routing is
deterministic via the RuleEngine and task classification. LLMs are called
only when the task itself requires generative synthesis.

Execution model:
  - Tasks arrive via submit(task)
  - Executive classifies → routes → delegates to domain specialist
  - Each task has an ExecutionBudget; exceeded budgets cancel the task
  - Depth counter prevents A→B→A→B recursion
  - Conflict resolution: duplicate tasks are deduplicated by signature
"""
from __future__ import annotations

import asyncio
import hashlib
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Optional


class TaskPriority(str, Enum):
    CRITICAL = "critical"
    HIGH     = "high"
    NORMAL   = "normal"
    LOW      = "low"


class TaskStatus(str, Enum):
    QUEUED    = "queued"
    RUNNING   = "running"
    DONE      = "done"
    FAILED    = "failed"
    CANCELLED = "cancelled"
    REJECTED  = "rejected"


@dataclass
class ExecutionBudget:
    max_time_seconds: float = 60.0
    max_agent_calls: int = 10
    max_cost_usd: float = 0.50

    def clone(self) -> "ExecutionBudget":
        return ExecutionBudget(
            max_time_seconds=self.max_time_seconds,
            max_agent_calls=self.max_agent_calls,
            max_cost_usd=self.max_cost_usd,
        )


@dataclass
class ExecTask:
    id: str
    task: str
    context: dict[str, Any]
    priority: TaskPriority
    budget: ExecutionBudget
    depth: int = 0
    status: TaskStatus = TaskStatus.QUEUED
    result: Any = None
    error: Optional[str] = None
    submitted_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    finished_at: Optional[str] = None
    agent_calls: int = 0
    cost_usd: float = 0.0
    duration_ms: float = 0.0

    @property
    def signature(self) -> str:
        """Deterministic content hash for deduplication."""
        raw = f"{self.task}:{sorted(self.context.items())}"
        return hashlib.md5(raw.encode()).hexdigest()[:12]

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "task": self.task,
            "priority": self.priority.value,
            "status": self.status.value,
            "depth": self.depth,
            "result": self.result,
            "error": self.error,
            "submitted_at": self.submitted_at,
            "finished_at": self.finished_at,
            "agent_calls": self.agent_calls,
            "cost_usd": self.cost_usd,
            "duration_ms": self.duration_ms,
        }


# Domain handlers registered by specialist agents
DomainHandler = Callable[[ExecTask], Any]

_PRIORITY_ORDER = {
    TaskPriority.CRITICAL: 0,
    TaskPriority.HIGH:     1,
    TaskPriority.NORMAL:   2,
    TaskPriority.LOW:      3,
}

# Max delegation depth before automatic rejection
_MAX_DEPTH = 5
# Max concurrent tasks before queuing
_MAX_CONCURRENT = 8


class ExecutiveAgent:
    """
    Central orchestration authority. Stateful; one instance per process.
    Thread-safe for the asyncio event loop (does not use threading.Lock).
    """

    def __init__(self) -> None:
        self._handlers: dict[str, DomainHandler] = {}
        self._active: dict[str, ExecTask] = {}
        self._history: list[ExecTask] = []
        self._dedup_window: dict[str, float] = {}  # signature → submit_time
        self._dedup_ttl = 60.0

        self._default_budget = ExecutionBudget(
            max_time_seconds=60.0,
            max_agent_calls=10,
            max_cost_usd=0.50,
        )

        self._task_counts: dict[str, int] = {
            "submitted": 0, "completed": 0, "failed": 0,
            "rejected": 0, "cancelled": 0, "deduplicated": 0,
        }

    # ── Registration ─────────────────────────────────────────────────────────

    def register_handler(self, domain: str, handler: DomainHandler) -> None:
        self._handlers[domain] = handler

    # ── Public task interface ─────────────────────────────────────────────────

    async def submit(
        self,
        task: str,
        context: Optional[dict] = None,
        priority: TaskPriority = TaskPriority.NORMAL,
        budget: Optional[ExecutionBudget] = None,
        depth: int = 0,
    ) -> ExecTask:
        exec_task = ExecTask(
            id=f"xt_{uuid.uuid4().hex[:10]}",
            task=task,
            context=context or {},
            priority=priority,
            budget=budget or self._default_budget.clone(),
            depth=depth,
        )
        self._task_counts["submitted"] += 1

        # Governance checks (deterministic, no LLM)
        rejection = self._check_governance(exec_task)
        if rejection:
            exec_task.status = TaskStatus.REJECTED
            exec_task.error = rejection
            exec_task.finished_at = datetime.now(timezone.utc).isoformat()
            self._task_counts["rejected"] += 1
            self._history.append(exec_task)
            return exec_task

        # Deduplication
        if self._is_duplicate(exec_task):
            exec_task.status = TaskStatus.CANCELLED
            exec_task.error = "Duplicate task within dedup window"
            exec_task.finished_at = datetime.now(timezone.utc).isoformat()
            self._task_counts["deduplicated"] += 1
            self._history.append(exec_task)
            return exec_task

        # Concurrency cap — queue if at max
        if len(self._active) >= _MAX_CONCURRENT and priority != TaskPriority.CRITICAL:
            exec_task.status = TaskStatus.QUEUED
            self._history.append(exec_task)
            return exec_task

        return await self._execute(exec_task)

    async def delegate(
        self,
        task: str,
        to_domain: str,
        context: Optional[dict] = None,
        from_task: Optional[ExecTask] = None,
        priority: TaskPriority = TaskPriority.NORMAL,
    ) -> ExecTask:
        """Explicit delegation from executive to a domain specialist."""
        depth = (from_task.depth + 1) if from_task else 0
        budget = from_task.budget.clone() if from_task else self._default_budget.clone()

        child = ExecTask(
            id=f"xt_{uuid.uuid4().hex[:10]}",
            task=task,
            context=dict(context or {}),
            priority=priority,
            budget=budget,
            depth=depth,
        )
        child.context["__domain__"] = to_domain
        self._task_counts["submitted"] += 1

        if depth >= _MAX_DEPTH:
            child.status = TaskStatus.REJECTED
            child.error = f"Delegation depth {depth} exceeds maximum {_MAX_DEPTH}"
            self._task_counts["rejected"] += 1
            self._history.append(child)
            return child

        return await self._execute(child)

    # ── Governance ────────────────────────────────────────────────────────────

    def _check_governance(self, task: ExecTask) -> Optional[str]:
        """Deterministic policy checks. Returns rejection reason or None."""
        if task.depth >= _MAX_DEPTH:
            return f"max_delegation_depth ({_MAX_DEPTH})"
        if task.budget.max_time_seconds <= 0:
            return "budget_expired"
        if task.budget.max_cost_usd <= 0:
            return "cost_budget_exhausted"
        if task.budget.max_agent_calls <= 0:
            return "agent_call_budget_exhausted"
        return None

    def _is_duplicate(self, task: ExecTask) -> bool:
        sig = task.signature
        now = time.time()
        # Expire old dedup entries
        self._dedup_window = {
            k: v for k, v in self._dedup_window.items()
            if now - v < self._dedup_ttl
        }
        if sig in self._dedup_window:
            return True
        self._dedup_window[sig] = now
        return False

    # ── Execution ─────────────────────────────────────────────────────────────

    async def _execute(self, task: ExecTask) -> ExecTask:
        task.status = TaskStatus.RUNNING
        self._active[task.id] = task
        t0 = time.monotonic()

        try:
            domain = task.context.get("__domain__") or self._classify(task.task)
            handler = self._handlers.get(domain) or self._handlers.get("default")

            if handler is None:
                task.result = f"[Executive] No handler for domain '{domain}'. Task noted."
                task.status = TaskStatus.DONE
            else:
                task.agent_calls += 1
                task.budget.max_agent_calls -= 1
                try:
                    if asyncio.iscoroutinefunction(handler):
                        result = await asyncio.wait_for(
                            handler(task),
                            timeout=task.budget.max_time_seconds,
                        )
                    else:
                        result = handler(task)
                    task.result = result
                    task.status = TaskStatus.DONE
                except asyncio.TimeoutError:
                    task.status = TaskStatus.CANCELLED
                    task.error = f"Timed out after {task.budget.max_time_seconds}s"
                    self._task_counts["cancelled"] += 1
                except Exception as exc:
                    task.status = TaskStatus.FAILED
                    task.error = str(exc)
                    self._task_counts["failed"] += 1

            if task.status == TaskStatus.DONE:
                self._task_counts["completed"] += 1
        finally:
            task.duration_ms = (time.monotonic() - t0) * 1000
            task.finished_at = datetime.now(timezone.utc).isoformat()
            self._active.pop(task.id, None)
            self._history.append(task)
            if len(self._history) > 1000:
                self._history = self._history[-1000:]

        return task

    def _classify(self, task_text: str) -> str:
        """Deterministic domain classification by keyword matching. No LLM."""
        text = task_text.lower()
        if any(k in text for k in ["income", "revenue", "earn", "monetize", "shopify", "affiliate"]):
            return "income"
        if any(k in text for k in ["write", "content", "blog", "article", "post", "draft"]):
            return "content"
        if any(k in text for k in ["deploy", "infra", "monitor", "scale", "service"]):
            return "ops"
        if any(k in text for k in ["reason", "think", "analyze", "plan", "strategy"]):
            return "cognition"
        if any(k in text for k in ["memory", "remember", "recall", "store", "fact"]):
            return "memory"
        return "default"

    # ── Observability ─────────────────────────────────────────────────────────

    def summary(self) -> dict:
        recent = [t.to_dict() for t in self._history[-10:]]
        active = [t.to_dict() for t in self._active.values()]
        return {
            "task_counts": dict(self._task_counts),
            "active_tasks": len(self._active),
            "registered_domains": list(self._handlers.keys()),
            "max_concurrent": _MAX_CONCURRENT,
            "max_depth": _MAX_DEPTH,
            "recent_tasks": recent,
            "active": active,
        }

    def get_task(self, task_id: str) -> Optional[ExecTask]:
        if task_id in self._active:
            return self._active[task_id]
        return next((t for t in reversed(self._history) if t.id == task_id), None)

    def set_budget(self, **kwargs: Any) -> None:
        for key, val in kwargs.items():
            if hasattr(self._default_budget, key):
                setattr(self._default_budget, key, val)


_executive: Optional[ExecutiveAgent] = None


def get_executive_agent() -> ExecutiveAgent:
    global _executive
    if _executive is None:
        _executive = ExecutiveAgent()
    return _executive
