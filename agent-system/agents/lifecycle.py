"""
ARIA Agent System — Lifecycle Manager.
Orquesta el ciclo completo de vida de las tareas entre los agentes.

Flujo completo:
  Task Created → Planner → Plan Generated → Execution → Step Result → Verification → (pass → continue / fail → retry or escalate)

Este módulo actúa como el "director de orquesta" que:
- Arranca/para todos los agentes coordinadamente
- Maneja el estado global de las tareas
- Decide cuándo reintentar, escalar o finalizar
- Provee puntos de entrada para API/WebSocket
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from agents.base import AgentBase
from agents.planner import PlannerAgent
from agents.execution import ExecutionAgent
from agents.verification import VerificationAgent
from core.messaging.bus import MessageBus
from core.messaging.types import (
    AgentMessage,
    AgentType,
    MessageType,
    TaskEvent,
)

logger = logging.getLogger("aria.lifecycle")


class TaskLifecycleError(Exception):
    """Error en el ciclo de vida de una tarea."""
    pass


class LifecycleManager:
    """
    Orquesta el ciclo completo de tareas.

    Responsabilidades:
    - Arrancar/detener todos los agentes
    - Crear tareas y publicarlas en el bus
    - Monitorear progreso de tareas activas
    - Manejar reintentos y escalación
    - Proveer estado en tiempo real vía WebSocket
    """

    def __init__(self, bus: MessageBus | None = None):
        self.bus = bus or MessageBus()
        self.agents: dict[AgentType, AgentBase] = {}
        self._active_tasks: dict[str, dict[str, Any]] = {}
        self._task_retries: dict[str, int] = {}
        self._running = False
        self._task_events: list[TaskEvent] = []
        self._max_retries_default = 3

    async def start(self) -> None:
        """Arranca el bus y todos los agentes."""
        if self._running:
            return

        logger.info("LifecycleManager: iniciando...")

        # 1. Arrancar Message Bus
        await self.bus.start()

        # 2. Crear y registrar agentes
        self.agents[AgentType.PLANNER] = PlannerAgent(bus=self.bus)
        self.agents[AgentType.EXECUTION] = ExecutionAgent(bus=self.bus)
        self.agents[AgentType.VERIFICATION] = VerificationAgent(bus=self.bus)

        # 3. Registrar el LifecycleManager como oyente de eventos clave
        self.bus.subscribe(MessageType.TASK_CREATED, self._on_task_event)
        self.bus.subscribe(MessageType.TASK_COMPLETED, self._on_task_event)
        self.bus.subscribe(MessageType.TASK_FAILED, self._on_task_event)
        self.bus.subscribe(MessageType.VERIFICATION_FAILED, self._on_verification_failed)

        # 4. Arrancar cada agente
        for agent_type, agent in self.agents.items():
            await agent.start(self.bus)

        self._running = True
        logger.info("LifecycleManager: %d agentes activos", len(self.agents))

    async def stop(self) -> None:
        """Detiene todos los agentes y el bus."""
        self._running = False

        # Detener agentes
        for agent_type, agent in self.agents.items():
            await agent.stop()

        # Detener bus
        await self.bus.stop()

        self.agents.clear()
        self._active_tasks.clear()
        logger.info("LifecycleManager: detenido")

    # ── Creación de Tareas ────────────────────────────────

    async def create_task(
        self,
        task_type: str,
        title: str = "",
        input_data: dict[str, Any] | None = None,
        max_retries: int = 3,
        session_id: str | None = None,
    ) -> str:
        """
        Crea una nueva tarea y la publica en el bus.
        Retorna el ID de la tarea.
        """
        import uuid
        task_id = uuid.uuid4().hex

        self._active_tasks[task_id] = {
            "id": task_id,
            "task_type": task_type,
            "title": title,
            "input": input_data or {},
            "status": "pending",
            "max_retries": max_retries,
            "retry_count": 0,
            "created_at": time.time(),
            "started_at": None,
            "completed_at": None,
        }
        self._task_retries[task_id] = 0

        logger.info(
            "LifecycleManager: tarea creada %s [%s] '%s'",
            task_id[:8],
            task_type,
            title[:50],
        )

        await self.bus.publish(AgentMessage(
            type=MessageType.TASK_CREATED,
            source=AgentType.ORCHESTRATOR,
            target=AgentType.PLANNER,
            task_id=task_id,
            payload={
                "task_type": task_type,
                "title": title,
                "input": input_data or {},
                "session_id": session_id,
                "max_retries": max_retries,
            },
        ))

        self._record_event(TaskEvent(
            task_id=task_id,
            status="pending",
            action="task.created",
            message=f"Tarea creada: {title}",
        ))

        return task_id

    async def cancel_task(self, task_id: str) -> bool:
        """Cancela una tarea activa."""
        if task_id not in self._active_tasks:
            logger.warning("LifecycleManager: tarea %s no encontrada", task_id[:8])
            return False

        self._active_tasks[task_id]["status"] = "cancelled"

        await self.bus.publish(AgentMessage(
            type=MessageType.TASK_CANCELLED,
            source=AgentType.ORCHESTRATOR,
            target=None,
            task_id=task_id,
            payload={"reason": "Cancelled by user"},
        ))

        self._record_event(TaskEvent(
            task_id=task_id,
            status="cancelled",
            action="task.cancelled",
            message="Tarea cancelada",
        ))

        return True

    # ── Manejo de Eventos ────────────────────────────────

    async def _on_task_event(self, message: AgentMessage) -> None:
        """Maneja eventos de cambio de estado de tareas."""
        task_id = message.task_id
        if not task_id:
            return

        # Actualizar estado interno
        task = self._active_tasks.get(task_id)
        if task:
            if message.type == MessageType.TASK_COMPLETED:
                task["status"] = "completed"
                task["completed_at"] = time.time()
                task["result"] = message.payload.get("results", [])
                self._record_event(TaskEvent(
                    task_id=task_id,
                    status="completed",
                    message="Tarea completada exitosamente",
                    action="task.completed",
                ))
            elif message.type == MessageType.TASK_FAILED:
                task["status"] = "failed"
                task["completed_at"] = time.time()
                task["error"] = message.payload.get("error", "Unknown error")
                self._record_event(TaskEvent(
                    task_id=task_id,
                    status="failed",
                    message=task["error"],
                    action="task.failed",
                ))

        logger.debug(
            "LifecycleManager: evento %s para tarea %s",
            message.type.value,
            task_id[:8],
        )

    async def _on_verification_failed(self, message: AgentMessage) -> None:
        """
        Maneja fallos de verificación.
        Decide: reintentar o escalar.
        """
        task_id = message.task_id
        if not task_id:
            return

        retry_count = self._task_retries.get(task_id, 0)
        task = self._active_tasks.get(task_id)
        max_retries = task.get("max_retries", self._max_retries_default) if task else self._max_retries_default

        if retry_count < max_retries:
            # Reintentar: notificar al Planner para re-planificar
            self._task_retries[task_id] = retry_count + 1
            logger.info(
                "LifecycleManager: reintentando tarea %s (intento %d/%d)",
                task_id[:8],
                retry_count + 1,
                max_retries,
            )

            await self.bus.publish(AgentMessage(
                type=MessageType.TASK_NEEDS_REVIEW,
                source=AgentType.ORCHESTRATOR,
                target=AgentType.PLANNER,
                task_id=task_id,
                payload={
                    "error": message.payload.get("errors", ["Verification failed"]),
                    "failed_step": message.payload.get("step"),
                    "partial_result": message.payload.get("partial_result", {}),
                    "previous_plan": (task or {}).get("plan"),
                    "input": (task or {}).get("input", {}),
                    "task_type": (task or {}).get("task_type", "custom"),
                    "retry_count": retry_count + 1,
                },
            ))

            self._record_event(TaskEvent(
                task_id=task_id,
                status="retrying",
                action=f"retry.{retry_count + 1}",
                message=f"Reintento {retry_count + 1}/{max_retries}",
            ))
        else:
            # Escalar: todos los reintentos agotados
            logger.warning(
                "LifecycleManager: tarea %s agotó reintentos (%d/%d)",
                task_id[:8],
                retry_count,
                max_retries,
            )

            if task:
                task["status"] = "failed"
                task["error"] = f"Agotó {max_retries} reintentos"

            await self.bus.publish(AgentMessage(
                type=MessageType.TASK_FAILED,
                source=AgentType.ORCHESTRATOR,
                target=None,
                task_id=task_id,
                payload={
                    "error": f"Tarea falló después de {max_retries} reintentos",
                    "partial_results": message.payload.get("partial_result", {}),
                    "max_retries": max_retries,
                },
            ))

            self._record_event(TaskEvent(
                task_id=task_id,
                status="failed",
                action="retries.exhausted",
                message=f"Agotó {max_retries} reintentos",
            ))

    # ── Estado y Reportes ─────────────────────────────────

    def get_task_status(self, task_id: str) -> dict[str, Any] | None:
        """Retorna el estado actual de una tarea."""
        task = self._active_tasks.get(task_id)
        if not task:
            return None
        return {
            "id": task["id"],
            "task_type": task.get("task_type"),
            "title": task.get("title"),
            "status": task.get("status"),
            "created_at": task.get("created_at"),
            "started_at": task.get("started_at"),
            "completed_at": task.get("completed_at"),
            "error": task.get("error"),
            "result": task.get("result"),
            "retry_count": self._task_retries.get(task_id, 0),
            "max_retries": task.get("max_retries", self._max_retries_default),
        }

    def list_active_tasks(self) -> list[dict[str, Any]]:
        """Lista todas las tareas activas (pending + running)."""
        return [
            self.get_task_status(task_id)
            for task_id, task in self._active_tasks.items()
            if task.get("status") in ("pending", "planning", "running", "retrying")
        ]

    def get_recent_events(self, limit: int = 50) -> list[TaskEvent]:
        """Retorna los eventos recientes (para WebSocket/SSE)."""
        return self._task_events[-limit:]

    @property
    def agent_stats(self) -> dict[str, dict[str, Any]]:
        """Estadísticas de todos los agentes."""
        return {
            agent_type.value: agent.stats
            for agent_type, agent in self.agents.items()
        }

    @property
    def stats(self) -> dict[str, Any]:
        """Estadísticas generales del LifecycleManager."""
        active = self.list_active_tasks()
        completed = [
            t for t in self._active_tasks.values()
            if t.get("status") == "completed"
        ]
        failed = [
            t for t in self._active_tasks.values()
            if t.get("status") == "failed"
        ]
        return {
            "running": self._running,
            "agents": list(self.agents.keys()),
            "tasks": {
                "total": len(self._active_tasks),
                "active": len(active),
                "completed": len(completed),
                "failed": len(failed),
            },
            "agent_stats": self.agent_stats,
        }

    def _record_event(self, event: TaskEvent) -> None:
        """Registra un evento en el historial."""
        self._task_events.append(event)
        # Mantener tamaño manejable
        if len(self._task_events) > 1000:
            self._task_events = self._task_events[-500:]