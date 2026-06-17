from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from enum import IntEnum, Enum
from typing import Callable

from apps.core.memory.redis_client import get_cache

_OBJECTIVES_KEY = "autonomy:objectives:v1"
_HISTORY_KEY = "autonomy:history:v1"
_OBJECTIVES_TTL = 86400 * 365
_HISTORY_TTL = 86400 * 90


class ObjectivePriority(IntEnum):
    CRITICAL = 1
    HIGH = 2
    NORMAL = 3
    LOW = 4


class ObjectiveStatus(str, Enum):
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class StrategicObjective:
    obj_id: str
    name: str
    description: str
    priority: ObjectivePriority
    frequency_hours: float
    handler_key: str
    enabled: bool = True
    last_run_ts: float = 0.0
    next_run_ts: float = 0.0
    total_runs: int = 0
    success_count: int = 0
    fail_count: int = 0
    total_value_usd: float = 0.0
    status: ObjectiveStatus = ObjectiveStatus.ACTIVE

    def is_due(self) -> bool:
        return time.time() >= self.next_run_ts

    @property
    def success_rate(self) -> float:
        total = self.success_count + self.fail_count
        return self.success_count / total if total > 0 else 0.0

    def schedule_next(self) -> None:
        self.next_run_ts = time.time() + self.frequency_hours * 3600

    def to_dict(self) -> dict:
        return {
            "obj_id": self.obj_id,
            "name": self.name,
            "description": self.description,
            "priority": int(self.priority),
            "frequency_hours": self.frequency_hours,
            "handler_key": self.handler_key,
            "enabled": self.enabled,
            "last_run_ts": self.last_run_ts,
            "next_run_ts": self.next_run_ts,
            "total_runs": self.total_runs,
            "success_count": self.success_count,
            "fail_count": self.fail_count,
            "total_value_usd": self.total_value_usd,
            "status": self.status.value,
        }

    @classmethod
    def from_dict(cls, d: dict) -> StrategicObjective:
        return cls(
            obj_id=d["obj_id"],
            name=d["name"],
            description=d["description"],
            priority=ObjectivePriority(d["priority"]),
            frequency_hours=d["frequency_hours"],
            handler_key=d["handler_key"],
            enabled=d.get("enabled", True),
            last_run_ts=d.get("last_run_ts", 0.0),
            next_run_ts=d.get("next_run_ts", 0.0),
            total_runs=d.get("total_runs", 0),
            success_count=d.get("success_count", 0),
            fail_count=d.get("fail_count", 0),
            total_value_usd=d.get("total_value_usd", 0.0),
            status=ObjectiveStatus(d.get("status", ObjectiveStatus.ACTIVE.value)),
        )


@dataclass
class ExecutionRecord:
    record_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    obj_id: str = ""
    started_at: float = field(default_factory=time.time)
    completed_at: float = 0.0
    success: bool = False
    value_generated_usd: float = 0.0
    error: str = ""
    output: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "record_id": self.record_id,
            "obj_id": self.obj_id,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "success": self.success,
            "value_generated_usd": self.value_generated_usd,
            "error": self.error,
            "output": self.output,
        }

    @classmethod
    def from_dict(cls, d: dict) -> ExecutionRecord:
        return cls(
            record_id=d["record_id"],
            obj_id=d["obj_id"],
            started_at=d["started_at"],
            completed_at=d.get("completed_at", 0.0),
            success=d.get("success", False),
            value_generated_usd=d.get("value_generated_usd", 0.0),
            error=d.get("error", ""),
            output=d.get("output", {}),
        )


class AutonomousScheduler:
    def __init__(self) -> None:
        self._objectives: dict[str, StrategicObjective] = {}
        self._handlers: dict[str, Callable] = {}
        self._initialized = False

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register_objective(self, obj: StrategicObjective) -> None:
        self._objectives[obj.obj_id] = obj

    def register_handler(self, key: str, handler: Callable) -> None:
        self._handlers[key] = handler

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    async def _load_objectives(self) -> dict[str, StrategicObjective]:
        try:
            cache = get_cache()
            data = await cache.get(_OBJECTIVES_KEY)
            if data and isinstance(data, dict):
                return {k: StrategicObjective.from_dict(v) for k, v in data.items()}
        except Exception:
            pass
        return {}

    async def _save_objectives(self, objectives: dict[str, StrategicObjective]) -> None:
        try:
            cache = get_cache()
            await cache.set(_OBJECTIVES_KEY, {k: v.to_dict() for k, v in objectives.items()}, ttl_seconds=_OBJECTIVES_TTL)
        except Exception:
            pass

    async def _load_history(self) -> list[ExecutionRecord]:
        try:
            cache = get_cache()
            data = await cache.get(_HISTORY_KEY)
            if data and isinstance(data, list):
                return [ExecutionRecord.from_dict(r) for r in data]
        except Exception:
            pass
        return []

    async def _save_history(self, records: list[ExecutionRecord]) -> None:
        try:
            cache = get_cache()
            await cache.set(_HISTORY_KEY, [r.to_dict() for r in records[-500:]], ttl_seconds=_HISTORY_TTL)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Core API
    # ------------------------------------------------------------------

    async def get_objectives(self) -> list[StrategicObjective]:
        stored = await self._load_objectives()
        # merge in-memory with persisted (in-memory takes precedence for registered)
        merged = {**stored, **self._objectives}
        return list(merged.values())

    async def run_due_objectives(self) -> list[ExecutionRecord]:
        objectives = await self.get_objectives()
        due = [o for o in objectives if o.enabled and o.status == ObjectiveStatus.ACTIVE and o.is_due()]
        if not due:
            return []

        results: list[ExecutionRecord] = list(
            await asyncio.gather(*[self._run_objective(o) for o in due], return_exceptions=False)
        )

        # persist updated objectives
        all_objs = {o.obj_id: o for o in objectives}
        for obj in due:
            all_objs[obj.obj_id] = obj
        await self._save_objectives(all_objs)

        # append to history
        history = await self._load_history()
        history.extend(results)
        await self._save_history(history)

        return results

    async def _run_objective(self, obj: StrategicObjective) -> ExecutionRecord:
        record = ExecutionRecord(obj_id=obj.obj_id, started_at=time.time())
        handler = self._handlers.get(obj.handler_key)
        try:
            if handler is not None:
                output = await handler(obj)
            else:
                output = {"skipped": True, "reason": f"No handler registered for '{obj.handler_key}'"}

            record.success = True
            record.output = output if isinstance(output, dict) else {"result": str(output)}
            record.value_generated_usd = record.output.get("value_usd", 0.0)
            obj.success_count += 1
            obj.total_value_usd += record.value_generated_usd
        except Exception as exc:
            record.success = False
            record.error = str(exc)
            obj.fail_count += 1
        finally:
            record.completed_at = time.time()
            obj.total_runs += 1
            obj.last_run_ts = record.started_at
            obj.schedule_next()

        return record

    async def continuous_loop(self, interval_seconds: int = 300) -> None:
        while True:
            try:
                await self.run_due_objectives()
            except Exception:
                pass
            await asyncio.sleep(interval_seconds)

    async def reprioritize(self) -> None:
        objectives = await self.get_objectives()
        changed = False
        for obj in objectives:
            value_per_run = obj.total_value_usd / max(obj.total_runs, 1)
            if value_per_run > 10 and obj.priority > ObjectivePriority.HIGH:
                obj.priority = ObjectivePriority(int(obj.priority) - 1)
                changed = True
            if obj.total_runs >= 5 and obj.success_rate < 0.2 and obj.status == ObjectiveStatus.ACTIVE:
                obj.status = ObjectiveStatus.PAUSED
                changed = True
        if changed:
            all_objs = {o.obj_id: o for o in objectives}
            await self._save_objectives(all_objs)

    async def history(self, limit: int = 50) -> list[ExecutionRecord]:
        records = await self._load_history()
        return records[-limit:]

    def summary(self) -> dict:
        objs = list(self._objectives.values())
        total_value = sum(o.total_value_usd for o in objs)
        total_success = sum(o.success_count for o in objs)
        total_runs = sum(o.total_runs for o in objs)
        return {
            "total_objectives": len(objs),
            "active": sum(1 for o in objs if o.status == ObjectiveStatus.ACTIVE),
            "paused": sum(1 for o in objs if o.status == ObjectiveStatus.PAUSED),
            "total_value_generated_usd": total_value,
            "success_rate_overall": total_success / max(total_runs, 1),
        }

    # ------------------------------------------------------------------
    # Default objectives
    # ------------------------------------------------------------------

    def _default_objectives(self) -> list[StrategicObjective]:
        now = time.time()
        return [
            StrategicObjective(
                obj_id="growth_loops_cycle",
                name="Growth Loops Cycle",
                description="Runs viral growth loops across all channels to compound user acquisition",
                priority=ObjectivePriority.HIGH,
                frequency_hours=6.0,
                handler_key="growth_loops_cycle",
                next_run_ts=now,
            ),
            StrategicObjective(
                obj_id="shopify_optimization",
                name="Shopify Store Optimization",
                description="Optimizes product listings, pricing, and conversions on Shopify",
                priority=ObjectivePriority.HIGH,
                frequency_hours=12.0,
                handler_key="shopify_optimization",
                next_run_ts=now,
            ),
            StrategicObjective(
                obj_id="content_generation",
                name="Content Generation",
                description="Auto-generates and publishes high-value content across channels",
                priority=ObjectivePriority.NORMAL,
                frequency_hours=8.0,
                handler_key="content_generation",
                next_run_ts=now,
            ),
            StrategicObjective(
                obj_id="market_intelligence",
                name="Market Intelligence",
                description="Gathers competitive intelligence and market trends",
                priority=ObjectivePriority.NORMAL,
                frequency_hours=24.0,
                handler_key="market_intelligence",
                next_run_ts=now,
            ),
            StrategicObjective(
                obj_id="crm_nurture",
                name="CRM Lead Nurture",
                description="Automatically nurtures leads and retains high-value customers",
                priority=ObjectivePriority.HIGH,
                frequency_hours=12.0,
                handler_key="crm_nurture",
                next_run_ts=now,
            ),
            StrategicObjective(
                obj_id="economic_rebalancing",
                name="Economic Rebalancing",
                description="Rebalances budget allocation across channels for maximum ROI",
                priority=ObjectivePriority.NORMAL,
                frequency_hours=24.0,
                handler_key="economic_rebalancing",
                next_run_ts=now,
            ),
        ]


_scheduler_instance: AutonomousScheduler | None = None


def get_autonomous_scheduler() -> AutonomousScheduler:
    global _scheduler_instance
    if _scheduler_instance is None:
        _scheduler_instance = AutonomousScheduler()
        for obj in _scheduler_instance._default_objectives():
            _scheduler_instance.register_objective(obj)
    return _scheduler_instance
