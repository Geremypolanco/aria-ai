"""
ARIA Agent System — Message Bus.
Comunicación asíncrona entre agentes usando asyncio.Queue + Redis Pub/Sub.
Soporta: publish, subscribe, request/reply, y colas de prioridad.
"""
from __future__ import annotations

import asyncio
import json
import logging
from collections import defaultdict
from datetime import datetime
from typing import Any, Callable, Coroutine

import redis.asyncio as aioredis
from core.config.settings import settings
from core.messaging.types import (
    AgentMessage,
    MessagePriority,
    MessageType,
)

logger = logging.getLogger("aria.bus")


class MessageBus:
    """
    Bus de mensajes para comunicación entre agentes.
    
    Características:
    - Publicación/suscripción por tipo de mensaje
    - Colas de prioridad (LOW, NORMAL, HIGH, CRITICAL)
    - Redis Pub/Sub para mensajes entre procesos
    - asyncio.Queue para mensajes locales
    - Timeout automático de mensajes expirados
    """

    def __init__(self, redis_url: str | None = None):
        self._redis_url = redis_url or str(settings.REDIS_URL)
        self._redis: aioredis.Redis | None = None
        self._pubsub: aioredis.Redis | None = None
        self._local_queues: dict[str, asyncio.Queue] = defaultdict(
            lambda: asyncio.Queue(maxsize=1000)
        )
        # Subscriptores: {MessageType: [callback, ...]}
        self._subscribers: dict[MessageType, list[Callable]] = defaultdict(list)
        self._running = False
        self._tasks: list[asyncio.Task] = []

    async def start(self) -> None:
        """Inicializa conexión Redis y arranca el bus."""
        if self._running:
            return

        try:
            self._redis = await aioredis.from_url(
                self._redis_url,
                decode_responses=True,
                socket_connect_timeout=5,
                socket_keepalive=True,
            )
            await self._redis.ping()
            self._pubsub = self._redis.pubsub()
            logger.info("MessageBus: conectado a Redis en %s", self._redis_url)
        except Exception as e:
            logger.warning("MessageBus: Redis no disponible, modo local-only: %s", e)
            self._redis = None

        self._running = True
        self._tasks.append(asyncio.create_task(self._process_local_messages()))
        if self._pubsub:
            self._tasks.append(asyncio.create_task(self._process_redis_messages()))
        logger.info("MessageBus: iniciado con %d subscriptores activos", len(self._subscribers))

    async def stop(self) -> None:
        """Detiene el bus y limpia recursos."""
        self._running = False
        for task in self._tasks:
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
        if self._redis:
            await self._redis.aclose()
            self._redis = None
        logger.info("MessageBus: detenido")

    # ── Publicación ───────────────────────────────────────

    async def publish(self, message: AgentMessage) -> bool:
        """
        Publica un mensaje en el bus.
        Los mensajes expirados se descartan silenciosamente.
        Retorna True si el mensaje fue encolado exitosamente.
        """
        if message.is_expired():
            logger.debug("MessageBus: mensaje expirado descartado: %s", message.id)
            return False

        # Publicar localmente
        try:
            await self._local_queues[message.type.value].put(message)
        except asyncio.QueueFull:
            logger.warning("MessageBus: cola llena para %s, descartando mensaje", message.type)
            return False

        # Publicar en Redis si está disponible
        if self._redis:
            try:
                payload = message.model_dump_json()
                await self._redis.publish(
                    f"aria:bus:{message.type.value}",
                    payload,
                )
            except Exception as e:
                logger.error("MessageBus: error publicando en Redis: %s", e)

        logger.debug(
            "MessageBus: publicado %s de %s -> %s [%s]",
            message.type.value,
            message.source,
            message.target or "*",
            message.id[:8],
        )
        return True

    # ── Suscripción ───────────────────────────────────────

    def subscribe(
        self,
        message_type: MessageType,
        callback: Callable[[AgentMessage], Coroutine[Any, Any, None]],
    ) -> None:
        """
        Registra un callback para un tipo de mensaje.
        El callback debe ser una coroutine async que recibe un AgentMessage.
        """
        self._subscribers[message_type].append(callback)
        logger.debug("MessageBus: subscriptor registrado para %s", message_type.value)

    def unsubscribe(
        self,
        message_type: MessageType,
        callback: Callable[[AgentMessage], Coroutine[Any, Any, None]],
    ) -> bool:
        """Elimina un subscriptor."""
        if callback in self._subscribers[message_type]:
            self._subscribers[message_type].remove(callback)
            return True
        return False

    # ── Request/Reply (patrón síncrono sobre bus asíncrono) ──

    _pending_requests: dict[str, asyncio.Future] = {}

    async def request(
        self,
        message: AgentMessage,
        timeout: float = 30.0,
    ) -> AgentMessage | None:
        """
        Envía un mensaje y espera una respuesta.
        Útil para: Planner solicita ejecución → espera respuesta.
        """
        reply_queue: asyncio.Queue[AgentMessage] = asyncio.Queue(maxsize=1)

        async def reply_handler(reply: AgentMessage) -> None:
            if reply.correlation_id == message.id:
                await reply_queue.put(reply)

        self.subscribe(MessageType.STEP_EXECUTED, reply_handler)
        self.subscribe(MessageType.STEP_FAILED, reply_handler)

        try:
            await self.publish(message)
            reply = await asyncio.wait_for(reply_queue.get(), timeout=timeout)
            return reply
        except asyncio.TimeoutError:
            logger.warning("MessageBus: request timeout para %s", message.id[:8])
            return None
        finally:
            self.unsubscribe(MessageType.STEP_EXECUTED, reply_handler)
            self.unsubscribe(MessageType.STEP_FAILED, reply_handler)

    # ── Procesamiento interno ─────────────────────────────

    async def _process_local_messages(self) -> None:
        """Procesa mensajes de las colas locales."""
        while self._running:
            try:
                # Escanea todas las colas con prioridad
                for msg_type, queue in self._local_queues.items():
                    if not queue.empty():
                        message: AgentMessage = await queue.get()
                        await self._dispatch(message)
                await asyncio.sleep(0.01)  # Evitar busy-wait
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("MessageBus: error en procesamiento local: %s", e)

    async def _process_redis_messages(self) -> None:
        """Procesa mensajes de Redis Pub/Sub (entre procesos)."""
        if not self._pubsub:
            return

        # Suscribirse a todos los canales de ARIA
        pattern = "aria:bus:*"
        await self._pubsub.psubscribe(pattern)

        try:
            async for message in self._pubsub.listen():
                if message["type"] != "pmessage":
                    continue
                try:
                    decoded = json.loads(message["data"])
                    agent_msg = AgentMessage(**decoded)
                    await self._dispatch(agent_msg)
                except Exception as e:
                    logger.error("MessageBus: error decodificando mensaje Redis: %s", e)
        except asyncio.CancelledError:
            pass

    async def _dispatch(self, message: AgentMessage) -> None:
        """Despacha un mensaje a los subscriptores correspondientes."""
        if message.is_expired():
            return

        # Despachar por tipo exacto
        callbacks = self._subscribers.get(message.type, [])
        if not callbacks:
            logger.debug("MessageBus: no hay subscriptores para %s", message.type.value)
            return

        results = await asyncio.gather(
            *[cb(message) for cb in callbacks],
            return_exceptions=True,
        )

        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error(
                    "MessageBus: error en callback %s para %s: %s",
                    callbacks[i].__name__,
                    message.type.value,
                    result,
                )
