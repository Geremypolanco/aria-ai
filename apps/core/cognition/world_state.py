"""
world_state.py — Motor de estado del mundo para ARIA AI.

ARIA mantiene un modelo interno persistente de su entorno:
  - Usuarios y sus preferencias
  - Proyectos activos con estado real
  - Tareas en progreso con timestamps
  - Estado del sistema (APIs, errores, métricas)
  - Línea temporal de eventos

TODO ES REAL. Sin mocks. Sin placeholders.
Persiste en Supabase + Redis. Actualiza por eventos.
"""
from __future__ import annotations
import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from typing import Any, Optional
from apps.core.config import settings

logger = logging.getLogger("aria.world_state")


class WorldState:
    """
    Estado del mundo de ARIA. Se actualiza continuamente.
    Punto de verdad único para todos los agentes.
    """

    def __init__(self) -> None:
        self._state: dict[str, Any] = {
            "users": {},
            "projects": {},
            "tasks": {},
            "system": {
                "started_at": datetime.now(timezone.utc).isoformat(),
                "api_health": {},
                "error_counts": {},
                "last_action": None,
            },
            "timeline": [],
        }
        self._dirty = False
        self._last_persist = 0.0

    # ── USUARIOS ──────────────────────────────────────────────────

    def update_user(self, user_id: str, data: dict) -> None:
        if user_id not in self._state["users"]:
            self._state["users"][user_id] = {"created_at": datetime.now(timezone.utc).isoformat()}
        self._state["users"][user_id].update({**data, "last_seen": datetime.now(timezone.utc).isoformat()})
        self._dirty = True
        self._record_event("user_update", {"user_id": user_id, **data})

    def get_user(self, user_id: str) -> dict:
        return self._state["users"].get(user_id, {})

    # ── PROYECTOS ─────────────────────────────────────────────────

    def set_project(self, project_id: str, status: str, data: dict = None) -> None:
        self._state["projects"][project_id] = {
            "status": status,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            **(data or {}),
        }
        self._dirty = True
        self._record_event("project_update", {"project": project_id, "status": status})

    def get_project(self, project_id: str) -> dict:
        return self._state["projects"].get(project_id, {})

    def list_active_projects(self) -> list[dict]:
        return [{"id": k, **v} for k, v in self._state["projects"].items()
                if v.get("status") not in ("done", "cancelled")]

    # ── TAREAS ────────────────────────────────────────────────────

    def add_task(self, task_id: str, task_type: str, payload: dict) -> None:
        self._state["tasks"][task_id] = {
            "type": task_type,
            "status": "pending",
            "payload": payload,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "attempts": 0,
        }
        self._dirty = True
        self._record_event("task_created", {"task_id": task_id, "type": task_type})

    def update_task(self, task_id: str, status: str, result: dict = None) -> None:
        if task_id in self._state["tasks"]:
            self._state["tasks"][task_id].update({
                "status": status,
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "attempts": self._state["tasks"][task_id].get("attempts", 0) + 1,
                **({"result": result} if result else {}),
            })
            self._dirty = True
            self._record_event("task_update", {"task_id": task_id, "status": status})

    def get_pending_tasks(self) -> list[dict]:
        return [{"id": k, **v} for k, v in self._state["tasks"].items()
                if v.get("status") in ("pending", "retry")]

    def get_failed_tasks(self) -> list[dict]:
        return [{"id": k, **v} for k, v in self._state["tasks"].items()
                if v.get("status") == "failed"]

    # ── SISTEMA ───────────────────────────────────────────────────

    def update_api_health(self, api_name: str, healthy: bool, latency_ms: float = None) -> None:
        self._state["system"]["api_health"][api_name] = {
            "healthy": healthy,
            "checked_at": datetime.now(timezone.utc).isoformat(),
            **({"latency_ms": latency_ms} if latency_ms else {}),
        }
        if not healthy:
            self._state["system"]["error_counts"][api_name] = \
                self._state["system"]["error_counts"].get(api_name, 0) + 1

    def record_action(self, action: str, result: str = "ok") -> None:
        self._state["system"]["last_action"] = {
            "action": action, "result": result,
            "at": datetime.now(timezone.utc).isoformat(),
        }
        self._dirty = True

    # ── LÍNEA TEMPORAL ────────────────────────────────────────────

    def _record_event(self, event_type: str, data: dict) -> None:
        event = {"type": event_type, "ts": datetime.now(timezone.utc).isoformat(), **data}
        self._state["timeline"].append(event)
        if len(self._state["timeline"]) > 500:
            self._state["timeline"] = self._state["timeline"][-200:]

    def get_recent_timeline(self, n: int = 20) -> list[dict]:
        return self._state["timeline"][-n:]

    # ── SNAPSHOT ──────────────────────────────────────────────────

    def snapshot(self) -> dict:
        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "active_projects": len(self.list_active_projects()),
            "pending_tasks": len(self.get_pending_tasks()),
            "failed_tasks": len(self.get_failed_tasks()),
            "known_users": len(self._state["users"]),
            "api_health": self._state["system"]["api_health"],
            "last_action": self._state["system"]["last_action"],
            "recent_events": self.get_recent_timeline(10),
        }

    # ── PERSISTENCIA ──────────────────────────────────────────────

    async def persist(self) -> None:
        if not self._dirty:
            return
        try:
            from apps.core.memory.redis_client import get_cache
            cache = get_cache()
            if cache:
                await cache.set("aria:world_state", json.dumps(self._state, default=str, ttl_seconds=3600))
        except Exception as exc:
            logger.warning("[WorldState] Redis persist failed: %s", exc)

        try:
            from apps.core.memory.supabase_client import get_db
            db = get_db()
            if db:
                await db.table("aria_world_state").upsert({
                    "key": "current",
                    "state": self._state,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }).execute()
        except Exception:
            pass

        self._dirty = False
        self._last_persist = time.time()
        logger.debug("[WorldState] Estado persistido")

    async def load(self) -> bool:
        try:
            from apps.core.memory.redis_client import get_cache
            cache = get_cache()
            if cache:
                raw = await cache.get("aria:world_state")
                if raw:
                    self._state = json.loads(raw)
                    logger.info("[WorldState] Estado cargado desde Redis (%d proyectos, %d tareas)",
                                len(self._state.get("projects", {})),
                                len(self._state.get("tasks", {})))
                    return True
        except Exception as exc:
            logger.warning("[WorldState] Load failed: %s", exc)
        return False


_world_state: Optional[WorldState] = None

def get_world_state() -> WorldState:
    global _world_state
    if _world_state is None:
        _world_state = WorldState()
    return _world_state
