"""
workflow_ledger.py — Ledger of Dynamic Workflow executions.

Every Deep Workflow that finishes is recorded here (goal, number of
subagents, verified/repaired, tokens, duration). It gives the user
**observability into their usage** — like the usage dashboards of frontier
AIs — and is the foundation of the "pay per outcome" model: the
`deliverables` (completed workflows) are the unit of value, not the tokens.

Storage: in memory (bounded ring per user). One Fly process = one ledger;
sufficient for the dashboard. If multi-instance persistence is ever needed,
this is the single point where Redis/DB would be plugged in.
"""

from __future__ import annotations

import threading
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

# How many recent runs are kept per user.
MAX_RUNS_PER_USER = 100


@dataclass
class WorkflowRun:
    goal: str
    subtasks: int
    verified: int
    repaired: int
    tokens: int
    duration_ms: int
    ok: bool
    ts: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "goal": self.goal,
            "subtasks": self.subtasks,
            "verified": self.verified,
            "repaired": self.repaired,
            "tokens": self.tokens,
            "duration_ms": self.duration_ms,
            "ok": self.ok,
            "ts": self.ts,
        }


class WorkflowLedger:
    """Thread-safe ledger of workflow executions, per user."""

    def __init__(self) -> None:
        self._runs: dict[str, deque[WorkflowRun]] = defaultdict(
            lambda: deque(maxlen=MAX_RUNS_PER_USER)
        )
        self._lock = threading.Lock()

    def record(
        self,
        email: str,
        *,
        goal: str,
        subtasks: int,
        verified: int,
        repaired: int,
        tokens: int,
        duration_ms: int,
        ok: bool,
    ) -> None:
        """Records a finished workflow. Never raises — accounting must never
        break the request that invokes it."""
        key = (email or "anon").strip().lower()
        run = WorkflowRun(
            goal=(goal or "").strip()[:160],
            subtasks=max(0, int(subtasks)),
            verified=max(0, int(verified)),
            repaired=max(0, int(repaired)),
            tokens=max(0, int(tokens)),
            duration_ms=max(0, int(duration_ms)),
            ok=bool(ok),
        )
        with self._lock:
            self._runs[key].appendleft(run)

    def recent(self, email: str, limit: int = 10) -> list[dict[str, Any]]:
        key = (email or "anon").strip().lower()
        with self._lock:
            runs = list(self._runs.get(key, ()))[: max(1, limit)]
        return [r.to_dict() for r in runs]

    def stats(self, email: str) -> dict[str, Any]:
        """Lifetime aggregates for the user (what ARIA has delivered)."""
        key = (email or "anon").strip().lower()
        with self._lock:
            runs = list(self._runs.get(key, ()))
        total = len(runs)
        subagents = sum(r.subtasks for r in runs)
        verified = sum(r.verified for r in runs)
        tokens = sum(r.tokens for r in runs)
        completed = sum(1 for r in runs if r.ok)
        verify_rate = round(verified / subagents * 100) if subagents else 0
        return {
            "deliverables": completed,  # completed workflows = unit of "pay per outcome"
            "workflows": total,
            "subagents": subagents,
            "verified": verified,
            "verify_rate_pct": verify_rate,
            "tokens": tokens,
        }


_ledger: WorkflowLedger | None = None


def get_workflow_ledger() -> WorkflowLedger:
    global _ledger
    if _ledger is None:
        _ledger = WorkflowLedger()
    return _ledger
