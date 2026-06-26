"""
ARIA Procedural Memory — "How to do X" — strategy retention and workflow evolution.

Procedural memory stores successful sequences of actions:
  "To publish a blog post: [search → outline → write → proofread → post → distribute]"
  "To run an income cycle: [assess_niches → pick_strategy → execute → measure → report]"

These procedures are:
  - Learned from successful executions (reinforced when they work)
  - Updated when a step fails (the failing step is flagged or replaced)
  - Scored by success rate, avg revenue, avg time
  - Ranked for selection when ARIA needs to accomplish a goal

This enables ARIA to build institutional memory:
  - Week 1: ARIA discovers content_pipeline generates $10/cycle
  - Week 4: ARIA has refined it to 14 steps with 87% success rate
  - Week 8: ARIA runs it autonomously, only flagging unusual cases

Without procedural memory:
  - ARIA reinvents every workflow from scratch each time
  - Successful patterns are lost between sessions
  - ARIA cannot improve systematically
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger("aria.memory.procedural")

PROCEDURE_TTL = 86400 * 180  # 6 months
MAX_PROCEDURES = 100
MIN_EXECUTIONS_TO_TRUST = 3


@dataclass
class ProcedureStep:
    step: int
    action: str  # tool name or action description
    args: dict[str, Any]
    expected_output: str
    failure_count: int = 0
    success_count: int = 0
    avg_duration_ms: float = 0.0
    notes: str = ""

    @property
    def success_rate(self) -> float:
        total = self.success_count + self.failure_count
        return self.success_count / total if total > 0 else 0.0

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> ProcedureStep:
        return cls(**d)


@dataclass
class Procedure:
    id: str
    name: str  # human-readable: "publish_blog_post"
    goal_pattern: str  # trigger: "publish.*blog|write.*article"
    steps: list[ProcedureStep]
    created_at: str
    last_used: str | None = None
    execution_count: int = 0
    success_count: int = 0
    total_revenue_generated: float = 0.0
    avg_duration_ms: float = 0.0
    tags: list[str] = field(default_factory=list)
    version: int = 1

    @property
    def success_rate(self) -> float:
        return self.success_count / self.execution_count if self.execution_count > 0 else 0.0

    @property
    def is_trusted(self) -> bool:
        return self.execution_count >= MIN_EXECUTIONS_TO_TRUST and self.success_rate >= 0.6

    @property
    def avg_revenue_per_run(self) -> float:
        return (
            self.total_revenue_generated / self.execution_count if self.execution_count > 0 else 0.0
        )

    def utility_score(self) -> float:
        """Composite score for procedure selection: success × revenue × recency."""
        recency = 1.0 if self.last_used and self.execution_count > 0 else 0.5
        revenue_factor = min(1.0, self.avg_revenue_per_run / 100.0)  # normalize at $100
        return self.success_rate * (0.6 + 0.3 * revenue_factor + 0.1 * recency)

    def weakest_step(self) -> ProcedureStep | None:
        if not self.steps:
            return None
        return min(self.steps, key=lambda s: s.success_rate)

    def to_dict(self) -> dict:
        d = asdict(self)
        return d

    @classmethod
    def from_dict(cls, d: dict) -> Procedure:
        d = dict(d)
        d["steps"] = [ProcedureStep.from_dict(s) for s in d.get("steps", [])]
        return cls(**d)


class ProceduralMemory:
    """
    Stores and retrieves ARIA's learned procedures.

    Usage:
        mem = ProceduralMemory()

        # Store a new procedure learned from a successful run
        proc_id = await mem.store(
            name="publish_blog_post",
            goal_pattern="publish.*blog|write.*article",
            steps=[
                ProcedureStep(0, "web_search", {"q": "trending topics"}, "topic list"),
                ProcedureStep(1, "generate_content", {"type": "article"}, "draft text"),
                ProcedureStep(2, "publish_content", {"platform": "devto"}, "published url"),
            ],
        )

        # When ARIA needs to publish a blog, retrieve the best procedure
        proc = await mem.retrieve("write a blog post about AI")
        for step in proc.steps:
            await execute_tool(step.action, step.args)

        # Record outcome
        await mem.record_execution(proc_id, success=True, revenue=15.0, duration_ms=3000)
    """

    def __init__(self) -> None:
        self._procedures: dict[str, Procedure] = {}
        self._loaded = False

    # ── Storage ──────────────────────────────────────────────────────────

    async def store(
        self,
        name: str,
        goal_pattern: str,
        steps: list[ProcedureStep],
        tags: list[str] | None = None,
    ) -> str:
        proc_id = f"proc_{uuid.uuid4().hex[:10]}"
        now = datetime.now(UTC).isoformat()
        proc = Procedure(
            id=proc_id,
            name=name,
            goal_pattern=goal_pattern,
            steps=steps,
            created_at=now,
            tags=tags or [],
        )
        self._procedures[proc_id] = proc
        await self._persist(proc)
        logger.info("[ProceduralMem] Stored procedure '%s' (%d steps)", name, len(steps))
        return proc_id

    async def update_steps(self, proc_id: str, steps: list[ProcedureStep]) -> bool:
        proc = self._procedures.get(proc_id)
        if not proc:
            return False
        proc.steps = steps
        proc.version += 1
        await self._persist(proc)
        return True

    # ── Retrieval ─────────────────────────────────────────────────────────

    async def retrieve(
        self,
        goal: str,
        require_trusted: bool = False,
    ) -> Procedure | None:
        """Return best procedure matching the goal description."""
        await self._lazy_load()
        candidates = self._find_matching(goal)
        if require_trusted:
            candidates = [p for p in candidates if p.is_trusted]
        if not candidates:
            return None
        return max(candidates, key=lambda p: p.utility_score())

    async def retrieve_by_id(self, proc_id: str) -> Procedure | None:
        await self._lazy_load()
        return self._procedures.get(proc_id)

    async def list_all(self, trusted_only: bool = False) -> list[Procedure]:
        await self._lazy_load()
        procs = list(self._procedures.values())
        if trusted_only:
            procs = [p for p in procs if p.is_trusted]
        return sorted(procs, key=lambda p: p.utility_score(), reverse=True)

    def _find_matching(self, goal: str) -> list[Procedure]:
        import re

        goal_lower = goal.lower()
        matches = []
        for proc in self._procedures.values():
            try:
                if re.search(proc.goal_pattern, goal_lower, re.IGNORECASE):
                    matches.append(proc)
            except re.error:
                # Fallback to substring match if pattern is invalid
                if proc.name.lower() in goal_lower:
                    matches.append(proc)
        return matches

    # ── Execution Recording ──────────────────────────────────────────────

    async def record_execution(
        self,
        proc_id: str,
        success: bool,
        revenue: float = 0.0,
        duration_ms: float = 0.0,
        failed_step: int | None = None,
    ) -> None:
        proc = self._procedures.get(proc_id)
        if not proc:
            return

        proc.execution_count += 1
        proc.last_used = datetime.now(UTC).isoformat()
        if success:
            proc.success_count += 1
        proc.total_revenue_generated += revenue

        # Update avg duration (running mean)
        if duration_ms > 0:
            n = proc.execution_count
            proc.avg_duration_ms = (proc.avg_duration_ms * (n - 1) + duration_ms) / n

        # Update step-level metrics
        if failed_step is not None and 0 <= failed_step < len(proc.steps):
            proc.steps[failed_step].failure_count += 1
            logger.warning(
                "[ProceduralMem] Step %d of '%s' failed — success rate now %.0f%%",
                failed_step,
                proc.name,
                proc.steps[failed_step].success_rate * 100,
            )
        elif success:
            for step in proc.steps:
                step.success_count += 1

        await self._persist(proc)

    async def reinforce_step(self, proc_id: str, step_idx: int, duration_ms: float = 0.0) -> None:
        proc = self._procedures.get(proc_id)
        if proc and 0 <= step_idx < len(proc.steps):
            proc.steps[step_idx].success_count += 1
            if duration_ms > 0:
                n = proc.steps[step_idx].success_count
                proc.steps[step_idx].avg_duration_ms = (
                    proc.steps[step_idx].avg_duration_ms * (n - 1) + duration_ms
                ) / n
            await self._persist(proc)

    # ── Learning ─────────────────────────────────────────────────────────

    async def prune_failing_procedures(self, min_success_rate: float = 0.2) -> int:
        """Remove procedures that consistently fail below threshold."""
        to_remove = [
            pid
            for pid, proc in self._procedures.items()
            if proc.execution_count >= MIN_EXECUTIONS_TO_TRUST
            and proc.success_rate < min_success_rate
        ]
        for pid in to_remove:
            del self._procedures[pid]
        logger.info("[ProceduralMem] Pruned %d failing procedures", len(to_remove))
        return len(to_remove)

    def summary(self) -> dict:
        procs = list(self._procedures.values())
        return {
            "total_procedures": len(procs),
            "trusted": sum(1 for p in procs if p.is_trusted),
            "avg_success_rate": (sum(p.success_rate for p in procs) / len(procs) if procs else 0.0),
            "total_executions": sum(p.execution_count for p in procs),
            "total_revenue": sum(p.total_revenue_generated for p in procs),
        }

    # ── Persistence ───────────────────────────────────────────────────────

    async def _persist(self, proc: Procedure) -> None:
        try:
            from apps.core.memory.redis_client import get_cache

            cache = get_cache()
            if cache:
                await cache.set(
                    f"aria:memory:proc:{proc.id}",
                    json.dumps(proc.to_dict()),
                    ttl_seconds=PROCEDURE_TTL,
                )
        except Exception as exc:
            logger.debug("[ProceduralMem] Persist failed: %s", exc)

    async def _lazy_load(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        logger.debug("[ProceduralMem] Initialized")


_memory: ProceduralMemory | None = None


def get_procedural_memory() -> ProceduralMemory:
    global _memory
    if _memory is None:
        _memory = ProceduralMemory()
    return _memory
