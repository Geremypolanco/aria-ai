"""Durable execution checkpoints for crash-resilient workflow resumption."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from apps.core.memory.redis_client import get_cache

_INDEX_PREFIX = "ckpt_index:"
_CKPT_PREFIX = "ckpt:"


@dataclass
class ExecutionCheckpoint:
    id: str
    workflow_id: str
    step_name: str
    step_index: int
    state: dict[str, Any]
    created_at: str
    ttl_hours: int = 24

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "workflow_id": self.workflow_id,
            "step_name": self.step_name,
            "step_index": self.step_index,
            "state": self.state,
            "created_at": self.created_at,
            "ttl_hours": self.ttl_hours,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ExecutionCheckpoint":
        return cls(
            id=d["id"],
            workflow_id=d["workflow_id"],
            step_name=d["step_name"],
            step_index=d["step_index"],
            state=d.get("state", {}),
            created_at=d["created_at"],
            ttl_hours=d.get("ttl_hours", 24),
        )


class CheckpointManager:
    async def save(
        self,
        workflow_id: str,
        step_name: str,
        step_index: int,
        state: dict[str, Any],
        ttl_hours: int = 24,
    ) -> str:
        ckpt = ExecutionCheckpoint(
            id=f"ckpt_{workflow_id}_{step_name}",
            workflow_id=workflow_id,
            step_name=step_name,
            step_index=step_index,
            state=state,
            created_at=datetime.now(timezone.utc).isoformat(),
            ttl_hours=ttl_hours,
        )
        cache = get_cache()
        key = f"{_CKPT_PREFIX}{workflow_id}:{step_name}"
        await cache.set(key, ckpt.to_dict(), ttl_seconds=ttl_hours * 3600)

        # Maintain ordered index for load_latest
        idx_key = f"{_INDEX_PREFIX}{workflow_id}"
        existing_raw = await cache.get(idx_key)
        steps: list[str] = (existing_raw if isinstance(existing_raw, list) else json.loads(existing_raw)) if existing_raw else []
        if step_name not in steps:
            steps.append(step_name)
        await cache.set(idx_key, steps, ttl_seconds=ttl_hours * 3600)

        return ckpt.id

    async def load(self, workflow_id: str, step_name: str) -> Optional[ExecutionCheckpoint]:
        cache = get_cache()
        raw = await cache.get(f"{_CKPT_PREFIX}{workflow_id}:{step_name}")
        if not raw:
            return None
        try:
            data = raw if isinstance(raw, dict) else json.loads(raw)
            return ExecutionCheckpoint.from_dict(data)
        except Exception:
            return None

    async def load_latest(self, workflow_id: str) -> Optional[ExecutionCheckpoint]:
        cache = get_cache()
        idx_raw = await cache.get(f"{_INDEX_PREFIX}{workflow_id}")
        if not idx_raw:
            return None
        steps: list[str] = idx_raw if isinstance(idx_raw, list) else json.loads(idx_raw)
        # Walk in reverse; return first valid checkpoint
        for step_name in reversed(steps):
            ckpt = await self.load(workflow_id, step_name)
            if ckpt is not None:
                return ckpt
        return None

    async def delete(self, workflow_id: str, step_name: str) -> bool:
        cache = get_cache()
        key = f"{_CKPT_PREFIX}{workflow_id}:{step_name}"
        deleted = await cache.delete(key)

        idx_key = f"{_INDEX_PREFIX}{workflow_id}"
        idx_raw = await cache.get(idx_key)
        if idx_raw:
            existing = idx_raw if isinstance(idx_raw, list) else json.loads(idx_raw)
            steps = [s for s in existing if s != step_name]
            await cache.set(idx_key, steps)

        return bool(deleted)

    async def clear_workflow(self, workflow_id: str) -> int:
        cache = get_cache()
        idx_key = f"{_INDEX_PREFIX}{workflow_id}"
        idx_raw = await cache.get(idx_key)
        if not idx_raw:
            return 0
        steps: list[str] = idx_raw if isinstance(idx_raw, list) else json.loads(idx_raw)
        count = 0
        for step_name in steps:
            if await cache.delete(f"{_CKPT_PREFIX}{workflow_id}:{step_name}"):
                count += 1
        await cache.delete(idx_key)
        return count

    async def resume_from(self, workflow_id: str) -> tuple[int, dict]:
        ckpt = await self.load_latest(workflow_id)
        if ckpt is None:
            return 0, {}
        return ckpt.step_index, ckpt.state


_manager: Optional[CheckpointManager] = None


def get_checkpoint_manager() -> CheckpointManager:
    global _manager
    if _manager is None:
        _manager = CheckpointManager()
    return _manager
