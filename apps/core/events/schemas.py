"""
Typed, immutable event schemas — the canonical contracts for ARIA's event fabric.

All events are frozen dataclasses. Every event carries:
  - event_id: globally unique UUID
  - event_type: string discriminator (used for routing)
  - correlation_id: traces an originating user/cycle request end-to-end
  - causation_id: direct parent event that caused this one
  - sequence: monotonically increasing per correlation_id (best-effort)
  - ts: Unix epoch (float) — immutable after creation
  - ts_iso: ISO-8601 string for human readability
  - payload: arbitrary JSON-serializable dict
  - version: schema version for forward compatibility

No field may be mutated after construction (frozen=True).
"""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


class EventType(StrEnum):
    # Cognition domain
    REASONING_STARTED = "cognition.reasoning.started"
    REASONING_COMPLETED = "cognition.reasoning.completed"
    PLAN_CREATED = "cognition.plan.created"
    PLAN_STEP_DONE = "cognition.plan.step_done"
    PIPELINE_RUN = "cognition.pipeline.run"

    # Memory domain
    FACT_STORED = "memory.fact.stored"
    FACT_RETRIEVED = "memory.fact.retrieved"
    MEMORY_CONFLICT = "memory.conflict.detected"
    MEMORY_PRUNED = "memory.pruned"

    # Agent domain
    AGENT_DELEGATED = "agent.delegated"
    AGENT_COMPLETED = "agent.completed"
    AGENT_FAILED = "agent.failed"
    BUDGET_EXCEEDED = "agent.budget.exceeded"

    # Business domain
    INCOME_CYCLE = "business.income.cycle"
    REVENUE_RECORDED = "business.revenue.recorded"
    OPPORTUNITY_SCORED = "business.opportunity.scored"

    # Runtime domain
    TASK_ENQUEUED = "runtime.task.enqueued"
    TASK_COMPLETED = "runtime.task.completed"
    TASK_FAILED = "runtime.task.failed"
    CHECKPOINT_SAVED = "runtime.checkpoint.saved"

    # Security domain
    ACCESS_DENIED = "security.access.denied"
    POLICY_OVERRIDE = "security.policy.override"

    # Observability domain
    HEALTH_CHECK = "observability.health.check"
    METRIC_RECORDED = "observability.metric.recorded"

    # System
    SYSTEM_STARTUP = "system.startup"
    SYSTEM_SHUTDOWN = "system.shutdown"
    DEAD_LETTER = "system.dead_letter"


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _now_ts() -> float:
    return datetime.now(UTC).timestamp()


def _new_id() -> str:
    return str(uuid.uuid4())


@dataclass(frozen=True)
class AriaEvent:
    event_type: EventType
    payload: dict[str, Any]
    event_id: str = field(default_factory=_new_id)
    correlation_id: str = field(default_factory=_new_id)
    causation_id: str | None = None
    sequence: int = 0
    ts: float = field(default_factory=_now_ts)
    ts_iso: str = field(default_factory=_now_iso)
    version: str = "1.0"
    source: str = "aria"

    def to_dict(self) -> dict:
        d = asdict(self)
        d["event_type"] = self.event_type.value
        return d

    @classmethod
    def from_dict(cls, d: dict) -> AriaEvent:
        d = dict(d)
        d["event_type"] = EventType(d["event_type"])
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})

    def derive(
        self,
        event_type: EventType,
        payload: dict[str, Any],
        source: str = "aria",
    ) -> AriaEvent:
        """Create a causally-linked child event inheriting the correlation chain."""
        return AriaEvent(
            event_type=event_type,
            payload=payload,
            correlation_id=self.correlation_id,
            causation_id=self.event_id,
            source=source,
        )


def cognition_event(
    event_type: EventType,
    payload: dict,
    correlation_id: str | None = None,
    causation_id: str | None = None,
) -> AriaEvent:
    return AriaEvent(
        event_type=event_type,
        payload=payload,
        correlation_id=correlation_id or _new_id(),
        causation_id=causation_id,
        source="cognition",
    )


def business_event(
    event_type: EventType,
    payload: dict,
    correlation_id: str | None = None,
) -> AriaEvent:
    return AriaEvent(
        event_type=event_type,
        payload=payload,
        correlation_id=correlation_id or _new_id(),
        source="business",
    )


def runtime_event(
    event_type: EventType,
    payload: dict,
    correlation_id: str | None = None,
    causation_id: str | None = None,
) -> AriaEvent:
    return AriaEvent(
        event_type=event_type,
        payload=payload,
        correlation_id=correlation_id or _new_id(),
        causation_id=causation_id,
        source="runtime",
    )
