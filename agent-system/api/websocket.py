"""
ARIA Agent System — WebSocket Handler.
Streaming de logs del agente en tiempo real hacia el frontend.
Implementación completa en Fase 5.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect

logger = logging.getLogger("aria.websocket")


class ConnectionManager:
    """
    Gestiona conexiones WebSocket activas.
    Permite enviar eventos a clientes específicos o broadcast.
    """

    def __init__(self):
        self._connections: dict[str, list[WebSocket]] = {}  # session_id -> [websockets]

    async def connect(self, websocket: WebSocket, session_id: str = "default") -> None:
        await websocket.accept()
        if session_id not in self._connections:
            self._connections[session_id] = []
        self._connections[session_id].append(websocket)
        logger.info("WebSocket conectado: sesión=%s, total=%d", session_id, len(self._connections[session_id]))

    async def disconnect(self, websocket: WebSocket, session_id: str = "default") -> None:
        if session_id in self._connections:
            self._connections[session_id].remove(websocket)
            if not self._connections[session_id]:
                del self._connections[session_id]
        logger.info("WebSocket desconectado: sesión=%s", session_id)

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


manager = ConnectionManager()


async def websocket_handler(websocket: WebSocket, session_id: str = "default"):
    """Maneja una conexión WebSocket individual."""
    await manager.connect(websocket, session_id)
    try:
        while True:
            data = await websocket.receive_text()
            msg = json.loads(data)
            # Eco por ahora — la lógica real en Fase 5
            await manager.send_to_session(session_id, {
                "type": "echo",
                "data": msg,
            })
    except WebSocketDisconnect:
        await manager.disconnect(websocket, session_id)
    except Exception as e:
        logger.error("WebSocket error: %s", e)
        await manager.disconnect(websocket, session_id)
