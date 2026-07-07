"""
ARIA Agent System — Retry Queue & Human Intervention.
Cuando un agente falla N veces, la tarea se mueve a una cola de 'intervención humana'
en PostgreSQL y se notifica al usuario vía WebSocket.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text

from core.db.connection import get_session
from api.websocket import ws_manager

logger = logging.getLogger("aria.resilience.retry_queue")


class InterventionQueue:
    """
    Cola de tareas que requieren intervención humana.

    Flujo:
    1. Tarea falla N veces → se mueve a intervention_queue
    2. Se notifica al usuario vía WebSocket
    3. Admin revisa y decide: reanudar, modificar o cancelar
    4. Si se reanuda, vuelve al ciclo Planner → Execution → Verification
    """

    async def add_to_intervention(
        self,
        task_id: str,
        reason: str,
        task_data: dict[str, Any],
        session_id: str | None = None,
    ) -> bool:
        """
        Mueve una tarea a la cola de intervención humana.

        - Persiste en PostgreSQL (tabla intervention_queue)
        - Notifica al usuario vía WebSocket
        - Registra el evento en task_logs
        """
        try:
            async with get_session() as session:
                await session.execute(
                    text("""
                        INSERT INTO intervention_queue (task_id, reason, task_data, status, session_id)
                        VALUES (:task_id, :reason, :task_data::jsonb, 'pending', :session_id)
                    """),
                    {
                        "task_id": task_id,
                        "reason": reason,
                        "task_data": json.dumps(task_data),
                        "session_id": session_id,
                    },
                )

            # Notificar vía WebSocket
            if session_id:
                await ws_manager.send_to_session(session_id, {
                    "type": "intervention_required",
                    "task_id": task_id,
                    "reason": reason,
                    "message": f"La tarea {task_id[:8]} requiere intervención humana: {reason[:200]}",
                })

            logger.warning(
                "InterventionQueue: tarea %s enviada a intervención: %s",
                task_id[:8],
                reason[:100],
            )
            return True

        except Exception as e:
            logger.error("Error añadiendo tarea a intervention queue: %s", e)
            return False

    async def list_pending(self) -> list[dict[str, Any]]:
        """Lista tareas pendientes de intervención."""
        try:
            async with get_session() as session:
                result = await session.execute(
                    text("""
                        SELECT id, task_id, reason, task_data, status, created_at
                        FROM intervention_queue
                        WHERE status = 'pending'
                        ORDER BY created_at ASC
                    """),
                )
                rows = result.fetchall()
                return [
                    {
                        "id": str(row.id),
                        "task_id": row.task_id,
                        "reason": row.reason,
                        "task_data": row.task_data,
                        "status": row.status,
                        "created_at": row.created_at.isoformat(),
                    }
                    for row in rows
                ]
        except Exception as e:
            logger.error("Error listando intervention queue: %s", e)
            return []

    async def resolve(
        self,
        intervention_id: str,
        resolution: str,
        resolution_note: str = "",
    ) -> bool:
        """
        Resuelve una intervención.

        resolution: 'retry' | 'modify' | 'cancel' | 'approve'
        """
        try:
            async with get_session() as session:
                await session.execute(
                    text("""
                        UPDATE intervention_queue SET
                            status = :resolution,
                            resolution_note = :note,
                            resolved_at = :now
                        WHERE id = :id AND status = 'pending'
                    """),
                    {
                        "id": intervention_id,
                        "resolution": resolution,
                        "note": resolution_note,
                        "now": datetime.now(timezone.utc),
                    },
                )

            logger.info(
                "InterventionQueue: intervención %s resuelta: %s",
                intervention_id[:8],
                resolution,
            )
            return True

        except Exception as e:
            logger.error("Error resolviendo intervention: %s", e)
            return False

    async def count_pending(self) -> int:
        """Cuenta tareas pendientes de intervención."""
        try:
            async with get_session() as session:
                result = await session.execute(
                    text("SELECT COUNT(*) FROM intervention_queue WHERE status = 'pending'"),
                )
                return result.scalar() or 0
        except Exception:
            return 0

    async def get_task_status(self, task_id: str) -> str | None:
        """Obtiene el estado de intervención de una tarea."""
        try:
            async with get_session() as session:
                result = await session.execute(
                    text("""
                        SELECT status FROM intervention_queue
                        WHERE task_id = :task_id
                        ORDER BY created_at DESC LIMIT 1
                    """),
                    {"task_id": task_id},
                )
                row = result.fetchone()
                return row.status if row else None
        except Exception:
            return None


# ── Retry Queue (reintentos con backoff exponencial) ──

class RetryQueue:
    """
    Cola de reintentos con backoff exponencial.

    TaskType → {retry_count, max_retries, backoff_seconds}
    """

    def __init__(self):
        self._backoffs: dict[str, float] = {
            "terminal": 5.0,
            "browser": 10.0,
            "research": 15.0,
            "extract": 10.0,
            "custom": 5.0,
        }

    def get_backoff(self, task_type: str, retry_count: int) -> float:
        """
        Calcula el backoff exponencial para un reintento.

        Fórmula: backoff_base * (2 ^ retry_count) + jitter
        """
        base = self._backoffs.get(task_type, 5.0)
        import random
        jitter = random.uniform(0, 0.5 * base)
        return min(base * (2 ** retry_count) + jitter, 120.0)  # Max 2 minutos

    async def schedule_retry(
        self,
        task_id: str,
        task_type: str,
        retry_count: int,
        max_retries: int,
    ) -> float:
        """
        Programa un reintento y retorna los segundos a esperar.

        Si retry_count >= max_retries, mueve a intervención humana.
        """
        if retry_count >= max_retries:
            logger.warning(
                "RetryQueue: tarea %s agotó reintentos (%d/%d)",
                task_id[:8],
                retry_count,
                max_retries,
            )
            return -1  # Señal de intervención

        backoff = self.get_backoff(task_type, retry_count)
        logger.info(
            "RetryQueue: tarea %s reintento %d/%d en %.1fs",
            task_id[:8],
            retry_count + 1,
            max_retries,
            backoff,
        )
        return backoff


# Singleton global
intervention_queue = InterventionQueue()
retry_queue = RetryQueue()