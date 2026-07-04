"""
ARIA Agent System — WebSocket Handler.
Streaming de logs del agente en tiempo real hacia el frontend.
Usa el Message Bus para recibir eventos y reenviarlos a clientes.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query

from api.server import lifecycle, bus
from core.messaging.types import AgentMessage, MessageType, TaskEvent

logger = logging.getLogger("aria.websocket")

router = APIRouter()


class ConnectionManager:
    """
    Gestiona conexiones WebSocket activas.
    Se suscribe al Message Bus para transmitir eventos en tiempo real.
    """

    def __init__(self):
        self._connections: dict[str, list[WebSocket]] = {}  # session_id -> [websockets]
        self._subscription_task: asyncio.Task | None = None
        self._running = False

    async def start(self) -> None:
        """Arranca la suscripción al bus de mensajes."""
        if self._running:
            return
        self._running = True
        self._subscription_task = asyncio.create_task(self._bus_listener())
        logger.info("WebSocket Manager: escuchando bus de mensajes")

    async def stop(self) -> None:
        """Detiene la suscripción."""
        self._running = False
        if self._subscription_task:
            self._subscription_task.cancel()
            try:
                await self._subscription_task
            except asyncio.CancelledError:
                pass

    async def _bus_listener(self) -> None:
        """Lee eventos del LifecycleManager y los envía a los websockets."""
        while self._running:
            try:
                events = lifecycle.get_recent_events(limit=10)
                for event in events:
                    event_dict = {
                        "type": "task_event",
                        "task_id": event.task_id,
                        "status": event.status,
                        "message": event.message,
                        "action": event.action,
                        "timestamp": event.timestamp.isoformat() if hasattr(event.timestamp, 'isoformat') else str(event.timestamp),
                    }
                    await self.broadcast(event_dict)

                await asyncio.sleep(0.5)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("WebSocket bus listener error: %s", e)
                await asyncio.sleep(1)

    async def connect(self, websocket: WebSocket, session_id: str = "default") -> None:
        await websocket.accept()
        if session_id not in self._connections:
            self._connections[session_id] = []
        self._connections[session_id].append(websocket)

        # Enviar estado inicial
        await self._send_initial_state(websocket)

        logger.info(
            "WebSocket conectado: sesión=%s, total=%d",
            session_id[:8] if len(session_id) > 8 else session_id,
            sum(len(ws) for ws in self._connections.values()),
        )

    async def disconnect(self, websocket: WebSocket, session_id: str = "default") -> None:
        if session_id in self._connections:
            self._connections[session_id].remove(websocket)
            if not self._connections[session_id]:
                del self._connections[session_id]
        logger.info(
            "WebSocket desconectado: sesión=%s",
            session_id[:8] if len(session_id) > 8 else session_id,
        )

    async def _send_initial_state(self, websocket: WebSocket) -> None:
        """Envía el estado actual del sistema al conectarse."""
        try:
            await websocket.send_json({
                "type": "system_state",
                "data": lifecycle.stats,
            })
        except Exception:
            pass

    async def send_to_session(self, session_id: str, event: dict[str, Any]) -> None:
        """Envía un evento a todos los websockets de una sesión."""
        if session_id not in self._connections:
            return
        dead_connections = []
        for ws in self._connections[session_id]:
            try:
                await ws.send_json(event)
            except Exception:
                dead_connections.append(ws)
        for ws in dead_connections:
            await self.disconnect(ws, session_id)

    async def broadcast(self, event: dict[str, Any]) -> None:
        """Envía un evento a TODAS las sesiones activas."""
        for session_id in list(self._connections.keys()):
            await self.send_to_session(session_id, event)

    @property
    def active_connections(self) -> int:
        return sum(len(ws_list) for ws_list in self._connections.values())


# Singleton del manager
ws_manager = ConnectionManager()


@router.websocket("/ws/chat")
async def websocket_chat(websocket: WebSocket, session_id: str = Query("default")):
    """WebSocket para chat en tiempo real con ARIA."""
    await ws_manager.connect(websocket, session_id)
    try:
        while True:
            data = await websocket.receive_text()
            msg = json.loads(data)

            if msg.get("type") == "chat":
                # Crear tarea y enviar progreso
                message = msg.get("message", "")

                # Notificar: tarea creada
                await ws_manager.send_to_session(session_id, {
                    "type": "status",
                    "message": "Procesando tu solicitud...",
                })

                task_id = await lifecycle.create_task(
                    task_type="custom",
                    title=message[:100],
                    input_data={"message": message, "stream": True},
                    session_id=session_id,
                )

                # Stream de logs de la tarea
                last_log_count = 0
                for _ in range(60):  # Timeout 30s
                    status = lifecycle.get_task_status(task_id)
                    if not status:
                        break

                    current_status = status.get("status", "unknown")

                    # Enviar update de estado
                    await ws_manager.send_to_session(session_id, {
                        "type": "task_status",
                        "task_id": task_id,
                        "status": current_status,
                        "message": f"Estado: {current_status}",
                    })

                    if current_status == "completed":
                        await ws_manager.send_to_session(session_id, {
                            "type": "result",
                            "task_id": task_id,
                            "data": status.get("result", []),
                            "message": "¡Tarea completada!",
                        })
                        break
                    elif current_status == "failed":
                        await ws_manager.send_to_session(session_id, {
                            "type": "error",
                            "task_id": task_id,
                            "error": status.get("error", "Error desconocido"),
                        })
                        break

                    await asyncio.sleep(0.5)

            elif msg.get("type") == "ping":
                await ws_manager.send_to_session(session_id, {
                    "type": "pong",
                    "timestamp": __import__("time").time(),
                })

    except WebSocketDisconnect:
        await ws_manager.disconnect(websocket, session_id)
    except Exception as e:
        logger.error("WebSocket error: %s", e)
        await ws_manager.disconnect(websocket, session_id)


@router.websocket("/ws/events")
async def websocket_events(websocket: WebSocket, session_id: str = Query("default")):
    """
    WebSocket para recibir eventos del sistema en tiempo real.
    (logs de agentes, cambios de estado, heartbeats)
    """
    await ws_manager.connect(websocket, session_id)
    try:
        while True:
            data = await websocket.receive_text()
            msg = json.loads(data)

            if msg.get("type") == "subscribe":
                task_id = msg.get("task_id")
                if task_id:
                    # Enviar logs existentes
                    from core.db.repository import TaskLogRepository
                    try:
                        logs = await TaskLogRepository.get_logs(task_id)
                        await ws_manager.send_to_session(session_id, {
                            "type": "logs",
                            "task_id": task_id,
                            "logs": logs,
                        })
                    except Exception:
                        pass

            elif msg.get("type") == "ping":
                await ws_manager.send_to_session(session_id, {"type": "pong"})

    except WebSocketDisconnect:
        await ws_manager.disconnect(websocket, session_id)
    except Exception as e:
        logger.error("WebSocket events error: %s", e)
        await ws_manager.disconnect(websocket, session_id)