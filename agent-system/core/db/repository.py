"""
ARIA Agent System — Database Repository.
Operaciones CRUD para tareas, logs y memoria de agentes.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text
from core.db.connection import get_session

logger = logging.getLogger("aria.db.repository")


class TaskRepository:
    """Repositorio de operaciones sobre la tabla tasks."""

    @staticmethod
    async def create(
        task_type: str,
        title: str = "",
        input_data: dict[str, Any] | None = None,
        priority: int = 5,
        max_retries: int = 3,
        created_by: str = "system",
        session_id: str | None = None,
    ) -> dict[str, Any] | None:
        """Crea una nueva tarea en la base de datos."""
        async with get_session() as session:
            result = await session.execute(
                text("""
                    INSERT INTO tasks (task_type, title, input, priority, max_retries, created_by, session_id)
                    VALUES (:task_type, :title, :input, :priority, :max_retries, :created_by, :session_id)
                    RETURNING id, status, task_type, title, created_at
                """),
                {
                    "task_type": task_type,
                    "title": title,
                    "input": json.dumps(input_data or {}),
                    "priority": priority,
                    "max_retries": max_retries,
                    "created_by": created_by,
                    "session_id": session_id,
                },
            )
            row = result.fetchone()
            if row:
                return {
                    "id": row.id,
                    "status": row.status,
                    "task_type": row.task_type,
                    "title": row.title,
                    "created_at": row.created_at.isoformat(),
                }
            return None

    @staticmethod
    async def get(task_id: str) -> dict[str, Any] | None:
        """Obtiene una tarea por ID."""
        async with get_session() as session:
            result = await session.execute(
                text("""
                    SELECT id, status, task_type, title, input, plan, result,
                           error_message, priority, retry_count, max_retries,
                           created_by, created_at, started_at, completed_at
                    FROM tasks WHERE id = :task_id
                """),
                {"task_id": task_id},
            )
            row = result.fetchone()
            if row:
                return {
                    "id": str(row.id),
                    "status": row.status,
                    "task_type": row.task_type,
                    "title": row.title,
                    "input": row.input,
                    "plan": row.plan,
                    "result": row.result,
                    "error": row.error_message,
                    "priority": row.priority,
                    "retry_count": row.retry_count,
                    "max_retries": row.max_retries,
                    "created_by": row.created_by,
                    "created_at": row.created_at.isoformat() if row.created_at else None,
                    "started_at": row.started_at.isoformat() if row.started_at else None,
                    "completed_at": row.completed_at.isoformat() if row.completed_at else None,
                }
            return None

    @staticmethod
    async def list(
        status: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Lista tareas con filtro opcional por estado."""
        async with get_session() as session:
            query = """
                SELECT id, status, task_type, title, created_at, started_at, completed_at, error_message
                FROM tasks
            """
            params: dict[str, Any] = {"limit": limit, "offset": offset}

            if status:
                query += " WHERE status = :status"
                params["status"] = status

            query += " ORDER BY created_at DESC LIMIT :limit OFFSET :offset"

            result = await session.execute(text(query), params)
            rows = result.fetchall()

            return [
                {
                    "id": str(row.id),
                    "status": row.status,
                    "task_type": row.task_type,
                    "title": row.title,
                    "created_at": row.created_at.isoformat() if row.created_at else None,
                    "started_at": row.started_at.isoformat() if row.started_at else None,
                    "completed_at": row.completed_at.isoformat() if row.completed_at else None,
                    "error": row.error_message,
                }
                for row in rows
            ]

    @staticmethod
    async def update_status(
        task_id: str,
        status: str,
        error_message: str | None = None,
    ) -> bool:
        """Actualiza el estado de una tarea."""
        async with get_session() as session:
            now = datetime.now(timezone.utc)
            result = await session.execute(
                text("""
                    UPDATE tasks SET
                        status = :status,
                        error_message = COALESCE(:error_message, error_message),
                        started_at = CASE
                            WHEN :status = 'running' AND started_at IS NULL THEN :now
                            ELSE started_at
                        END,
                        completed_at = CASE
                            WHEN :status IN ('completed', 'failed', 'cancelled') THEN :now
                            ELSE completed_at
                        END
                    WHERE id = :task_id
                """),
                {
                    "task_id": task_id,
                    "status": status,
                    "error_message": error_message,
                    "now": now,
                },
            )
            return result.rowcount > 0

    @staticmethod
    async def update_plan(task_id: str, plan: dict[str, Any]) -> bool:
        """Guarda el plan generado por el PlannerAgent."""
        async with get_session() as session:
            result = await session.execute(
                text("""
                    UPDATE tasks SET
                        plan = :plan::jsonb,
                        status = 'planning'
                    WHERE id = :task_id
                """),
                {"task_id": task_id, "plan": json.dumps(plan)},
            )
            return result.rowcount > 0

    @staticmethod
    async def update_result(task_id: str, result_data: dict[str, Any]) -> bool:
        """Guarda el resultado de una tarea."""
        async with get_session() as session:
            result = await session.execute(
                text("""
                    UPDATE tasks SET
                        result = :result::jsonb,
                        status = 'completed',
                        completed_at = :now
                    WHERE id = :task_id
                """),
                {
                    "task_id": task_id,
                    "result": json.dumps(result_data),
                    "now": datetime.now(timezone.utc),
                },
            )
            return result.rowcount > 0

    @staticmethod
    async def count(status: str | None = None) -> int:
        """Cuenta tareas, opcionalmente filtradas por estado."""
        async with get_session() as session:
            if status:
                result = await session.execute(
                    text("SELECT COUNT(*) FROM tasks WHERE status = :status"),
                    {"status": status},
                )
            else:
                result = await session.execute(text("SELECT COUNT(*) FROM tasks"))
            return result.scalar() or 0


class TaskLogRepository:
    """Repositorio para logs de tareas."""

    @staticmethod
    async def add_log(
        task_id: str,
        agent_type: str,
        step: int,
        action: str,
        input_data: dict[str, Any] | None = None,
        output_data: dict[str, Any] | None = None,
        status: str = "success",
        duration_ms: int = 0,
        level: str = "info",
        message: str | None = None,
    ) -> bool:
        """Añade un log a una tarea."""
        async with get_session() as session:
            result = await session.execute(
                text("""
                    INSERT INTO task_logs (task_id, agent_type, step, action, input, output, status, duration_ms, level, message)
                    VALUES (:task_id, :agent_type::agent_type, :step, :action, :input::jsonb, :output::jsonb, :status, :duration_ms, :level::log_level, :message)
                """),
                {
                    "task_id": task_id,
                    "agent_type": agent_type,
                    "step": step,
                    "action": action,
                    "input": json.dumps(input_data or {}),
                    "output": json.dumps(output_data or {}),
                    "status": status,
                    "duration_ms": duration_ms,
                    "level": level,
                    "message": message,
                },
            )
            return result.rowcount > 0

    @staticmethod
    async def get_logs(task_id: str, limit: int = 50) -> list[dict[str, Any]]:
        """Obtiene los logs de una tarea."""
        async with get_session() as session:
            result = await session.execute(
                text("""
                    SELECT id, agent_type, step, action, status, duration_ms, level, message, created_at
                    FROM task_logs
                    WHERE task_id = :task_id
                    ORDER BY created_at ASC
                    LIMIT :limit
                """),
                {"task_id": task_id, "limit": limit},
            )
            rows = result.fetchall()
            return [
                {
                    "id": str(row.id),
                    "agent": row.agent_type,
                    "step": row.step,
                    "action": row.action,
                    "status": row.status,
                    "duration_ms": row.duration_ms,
                    "level": row.level,
                    "message": row.message,
                    "timestamp": row.created_at.isoformat(),
                }
                for row in rows
            ]