"""
ARIA Agent System — Clase Base para todos los Agentes.
Define el ciclo de vida estándar: init → run → handle_message → cleanup.
Todos los agentes heredan de aquí y se registran automáticamente en el Message Bus.
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from abc import ABC, abstractmethod
from typing import Any

from core.messaging.bus import MessageBus
from core.messaging.types import (
    AgentMessage,
    AgentType,
    MessageType,
    LogLevel,
)

logger = logging.getLogger("aria.agent")


class AgentBase(ABC):
    """
    Clase base abstracta para todos los agentes ARIA.

    Ciclo de vida:
      1. __init__: configura identidad y dependencias
      2. start(): registra subscriptores y arranca loop interno
      3. handle_message(callback): procesa mensajes entrantes
      4. stop(): limpia subscriptores y recursos
    """

    def __init__(
        self,
        agent_type: AgentType,
        agent_id: str | None = None,
        bus: MessageBus | None = None,
    ):
        self.agent_type = agent_type
        self.agent_id = agent_id or f"{agent_type.value}-{uuid.uuid4().hex[:8]}"
        self.bus = bus
        self._running = False
        self._task: asyncio.Task | None = None
        self._message_count = 0
        self._error_count = 0
        self._started_at: float | None = None

    # ── Propiedades ───────────────────────────────────────

    @property
    def uptime_seconds(self) -> float:
        if self._started_at is None:
            return 0.0
        return time.time() - self._started_at

    @property
    def stats(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "agent_type": self.agent_type.value,
            "uptime_seconds": round(self.uptime_seconds, 1),
            "messages_processed": self._message_count,
            "errors": self._error_count,
            "running": self._running,
        }

    # ── Ciclo de Vida ─────────────────────────────────────

    async def start(self, bus: MessageBus) -> None:
        """
        Inicializa el agente:
        - Conecta al Message Bus
        - Registra subscriptores para los tipos de mensaje relevantes
        - Arranca el loop de heartbeat
        """
        self.bus = bus
        self._running = True
        self._started_at = time.time()

        # Registrar subscriptores específicos de cada agente
        subscriptions = self.get_subscriptions()
        for msg_type in subscriptions:
            self.bus.subscribe(msg_type, self._on_message_wrapper)
            logger.debug(
                "%s [%s]: subscripto a %s",
                self.agent_type.value,
                self.agent_id[:8],
                msg_type.value,
            )

        # Heartbeat loop
        self._task = asyncio.create_task(self._heartbeat_loop())

        logger.info(
            "%s [%s]: iniciado con %d subscriptores",
            self.agent_type.value,
            self.agent_id[:8],
            len(subscriptions),
        )

    async def stop(self) -> None:
        """Detiene el agente y limpia recursos."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info(
            "%s [%s]: detenido (mensajes=%d, errores=%d)",
            self.agent_type.value,
            self.agent_id[:8],
            self._message_count,
            self._error_count,
        )

    # ── Subscriptores ─────────────────────────────────────

    @abstractmethod
    def get_subscriptions(self) -> list[MessageType]:
        """
        Retorna la lista de MessageType a los que este agente se suscribe.
        Cada agente concreto define sus suscripciones aquí.
        """
        ...

    # ── Manejo de Mensajes ────────────────────────────────

    async def _on_message_wrapper(self, message: AgentMessage) -> None:
        """Wrapper con logging, medición y manejo de errores."""
        if not self._running:
            return

        start = time.time()
        self._message_count += 1

        try:
            await self.handle_message(message)
            duration_ms = int((time.time() - start) * 1000)
            logger.debug(
                "%s [%s]: procesado %s en %dms",
                self.agent_type.value,
                self.agent_id[:8],
                message.type.value,
                duration_ms,
            )
        except Exception as e:
            self._error_count += 1
            duration_ms = int((time.time() - start) * 1000)
            logger.error(
                "%s [%s]: error procesando %s: %s (dur=%dms)",
                self.agent_type.value,
                self.agent_id[:8],
                message.type.value,
                e,
                duration_ms,
                exc_info=True,
            )

    @abstractmethod
    async def handle_message(self, message: AgentMessage) -> None:
        """
        Procesa un mensaje entrante.
        Cada agente implementa su lógica aquí.
        """
        ...

    # ── Publicación de Mensajes ───────────────────────────

    async def publish(self, message: AgentMessage) -> bool:
        """Publica un mensaje en el bus."""
        if self.bus is None:
            logger.warning("%s: bus no disponible, no se puede publicar", self.agent_id[:8])
            return False
        # Asegurar que source es este agente
        message.source = self.agent_type
        return await self.bus.publish(message)

    async def send_error(
        self,
        task_id: str,
        error: str,
        target: AgentType | None = None,
        correlation_id: str | None = None,
    ) -> None:
        """Envía un mensaje de error al bus."""
        await self.publish(AgentMessage(
            type=MessageType.AGENT_ERROR,
            source=self.agent_type,
            target=target,
            task_id=task_id,
            payload={"error": error},
            correlation_id=correlation_id,
        ))

    # ── Heartbeat ─────────────────────────────────────────

    async def _heartbeat_loop(self) -> None:
        """Publica heartbeat periódicamente."""
        while self._running:
            try:
                await self.publish(AgentMessage(
                    type=MessageType.AGENT_HEARTBEAT,
                    source=self.agent_type,
                    target=None,
                    payload=self.stats,
                ))
                await asyncio.sleep(30)  # Cada 30 segundos
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning("%s: heartbeat error: %s", self.agent_id[:8], e)
                await asyncio.sleep(5)